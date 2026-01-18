# app/main.py
import json
import os
import random
import re
import time
import math
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from starlette.middleware.sessions import SessionMiddleware

from app.db import JsonStore, find_by_id, find_index_by_id, new_id
from app.paypal import capture_order, create_order, get_client_id

# -------------------------
# Env loader (.env o env)
# -------------------------
def load_env() -> None:
    for p in (".env", "env"):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env()

# -------------------------
# App
# -------------------------
app = FastAPI(title="Cultural Routes MVP")

# Sessions
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev_secret_change_me").strip()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
store = JsonStore()

CATEGORIES = ["comida", "historico", "parque", "artesania"]

# Password hashing (evita bcrypt drama en Windows)
pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# -------------------------
# DB helpers (compatibles)
# -------------------------
def _db() -> dict:
    db = store.read()
    db.setdefault("listings", [])
    db.setdefault("bookings", [])
    db.setdefault("users", [])
    db.setdefault("businesses", [])
    return db


def _save(db: dict) -> None:
    db.setdefault("listings", [])
    db.setdefault("bookings", [])
    db.setdefault("users", [])
    db.setdefault("businesses", [])
    store.write(db)


def get_routes(db: dict) -> list[str]:
    """
    Mejora: siempre incluye 4 rutas base (incluye Ecuador),
    además agrega rutas encontradas en listings y businesses.
    """
    listings = db.get("listings", []) or []
    businesses = db.get("businesses", []) or []

    found = []
    for l in listings:
        r = (l.get("route") or "").strip()
        if r:
            found.append(r)

    for b in businesses:
        r = (b.get("route") or "").strip()
        if r:
            found.append(r)

    defaults = ["Ruta Spondylus / Montañita", "Cuenca", "Tena", "Ecuador"]

    out = []
    seen = set()
    for r in defaults + found:
        r = (r or "").strip()
        if not r or r in seen:
            continue
        seen.add(r)
        out.append(r)

    return out


# -------------------------
# Auth helpers
# -------------------------
def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def current_user(request: Request) -> Optional[dict]:
    s = request.session.get("user")
    if not s or not isinstance(s, dict):
        return None
    user_id = s.get("id")
    if not user_id:
        request.session.pop("user", None)
        return None

    db = _db()
    u = next((x for x in db["users"] if x.get("id") == user_id), None)
    if not u:
        request.session.pop("user", None)
        return None
    return u


def require_auth(request: Request) -> dict:
    u = current_user(request)
    if not u:
        raise HTTPException(status_code=401, detail="No autenticado")
    return u


def require_role(u: dict, role: str) -> None:
    if (u.get("role") or "").lower() != (role or "").lower():
        raise HTTPException(status_code=403, detail="No autorizado")


def tpl(request: Request, name: str, ctx: dict):
    ctx = dict(ctx or {})
    ctx["request"] = request
    ctx.setdefault("user", current_user(request))
    return templates.TemplateResponse(name, ctx)


def _clean(s: str) -> str:
    return (s or "").strip()


def _digits_phone(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _valid_url(u: str) -> bool:
    u = _clean(u)
    if not u:
        return True
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def validate_password_pair(password: str, confirm_password: str) -> Optional[str]:
    password = password or ""
    confirm_password = confirm_password or ""
    if password != confirm_password:
        return "Las contraseñas no coinciden."
    if len(password) < 8 or len(password) > 128:
        return "Contraseña inválida (8-128 caracteres)."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "La contraseña debe tener al menos 1 letra y 1 número."
    return None


def validate_common_user_fields(full_name: str, email: str, phone: str) -> tuple[str, str, str] | str:
    full_name = _clean(full_name)
    email = normalize_email(email)
    phone = _clean(phone)

    if len(full_name) < 2 or len(full_name) > 80:
        return "Nombre inválido (2-80 caracteres)."
    if not EMAIL_RE.match(email):
        return "Email inválido."
    digits = _digits_phone(phone)
    if len(digits) < 8 or len(digits) > 15:
        return "Teléfono inválido (8-15 dígitos)."
    return full_name, email, phone


def find_user_by_email_and_role(users: list[dict], email: str, role: str) -> Optional[dict]:
    e = normalize_email(email)
    r = (role or "").strip().lower()
    return next((u for u in users if normalize_email(u.get("email", "")) == e and (u.get("role") or "").lower() == r), None)


def email_exists_with_other_role(users: list[dict], email: str, role: str) -> Optional[dict]:
    e = normalize_email(email)
    r = (role or "").strip().lower()
    return next((u for u in users if normalize_email(u.get("email", "")) == e and (u.get("role") or "").lower() != r), None)


def find_business_by_owner(businesses: list[dict], owner_user_id: str) -> Optional[dict]:
    return next((b for b in businesses if b.get("owner_user_id") == owner_user_id), None)


# -------------------------
# Basic
# -------------------------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/")
def home():
    return RedirectResponse(url="/start", status_code=302)


# -------------------------
# Start / Role selector (auto logout)
# -------------------------
@app.get("/start")
def start(request: Request):
    request.session.clear()
    return tpl(request, "start.html", {"nav_mode": "auth"})


# -------------------------
# Auth Turista
# -------------------------
@app.get("/auth/tourist/login")
def tourist_login_page(request: Request):
    request.session.clear()
    return tpl(request, "auth_tourist_login.html", {"error": None, "nav_mode": "auth"})


@app.post("/auth/tourist/login")
def tourist_login(request: Request, email: str = Form(...), password: str = Form(...)):
    email_norm = normalize_email(email)
    password = password or ""

    if not EMAIL_RE.match(email_norm) or not password:
        return tpl(request, "auth_tourist_login.html", {"error": "Credenciales inválidas.", "nav_mode": "auth"})

    db = _db()
    other = email_exists_with_other_role(db["users"], email_norm, "tourist")
    if other:
        return tpl(request, "auth_tourist_login.html", {
            "error": "Ese email pertenece a COMERCIANTE. Entra por Login Comerciante.",
            "nav_mode": "auth"
        })

    user = find_user_by_email_and_role(db["users"], email_norm, "tourist")
    if not user or not pwd.verify(password, user.get("password_hash", "")):
        return tpl(request, "auth_tourist_login.html", {"error": "Credenciales inválidas.", "nav_mode": "auth"})

    request.session["user"] = {"id": user["id"]}
    return RedirectResponse(url="/listings", status_code=303)


@app.get("/auth/tourist/register")
def tourist_register_page(request: Request):
    request.session.clear()
    return tpl(request, "auth_tourist_register.html", {"error": None, "nav_mode": "auth"})


@app.post("/auth/tourist/register")
def tourist_register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    country: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    consent: str = Form(""),
):
    v = validate_common_user_fields(full_name, email, phone)
    if isinstance(v, str):
        return tpl(request, "auth_tourist_register.html", {"error": v, "nav_mode": "auth"})
    full_name, email_norm, phone = v

    country = _clean(country)
    if len(country) < 2 or len(country) > 60:
        return tpl(request, "auth_tourist_register.html", {"error": "País inválido.", "nav_mode": "auth"})

    pw_err = validate_password_pair(password, confirm_password)
    if pw_err:
        return tpl(request, "auth_tourist_register.html", {"error": pw_err, "nav_mode": "auth"})

    if not consent:
        return tpl(request, "auth_tourist_register.html", {"error": "Debes aceptar el consentimiento.", "nav_mode": "auth"})

    db = _db()
    if any(normalize_email(u.get("email", "")) == email_norm for u in db["users"]):
        other = email_exists_with_other_role(db["users"], email_norm, "tourist")
        if other:
            return tpl(request, "auth_tourist_register.html", {
                "error": "Ese email ya está registrado como COMERCIANTE. Usa otro email o entra como comerciante.",
                "nav_mode": "auth",
            })
        return tpl(request, "auth_tourist_register.html", {"error": "Ese email ya existe. Inicia sesión.", "nav_mode": "auth"})

    user_id = new_id("u")
    db["users"].append({
        "id": user_id,
        "role": "tourist",
        "full_name": full_name,
        "email": email_norm,
        "phone": phone,
        "country": country,
        "password_hash": pwd.hash(password),
        "created_at": int(time.time()),
    })
    _save(db)

    request.session["user"] = {"id": user_id}
    return RedirectResponse(url="/listings", status_code=303)


# -------------------------
# Auth Comerciante
# -------------------------
@app.get("/auth/merchant/login")
def merchant_login_page(request: Request):
    request.session.clear()
    return tpl(request, "auth_merchant_login.html", {"error": None, "nav_mode": "auth"})


@app.post("/auth/merchant/login")
def merchant_login(request: Request, email: str = Form(...), password: str = Form(...)):
    email_norm = normalize_email(email)
    password = password or ""

    if not EMAIL_RE.match(email_norm) or not password:
        return tpl(request, "auth_merchant_login.html", {"error": "Credenciales inválidas.", "nav_mode": "auth"})

    db = _db()
    other = email_exists_with_other_role(db["users"], email_norm, "merchant")
    if other:
        return tpl(request, "auth_merchant_login.html", {
            "error": "Ese email pertenece a TURISTA. Entra por Login Turista.",
            "nav_mode": "auth"
        })

    user = find_user_by_email_and_role(db["users"], email_norm, "merchant")
    if not user or not pwd.verify(password, user.get("password_hash", "")):
        return tpl(request, "auth_merchant_login.html", {"error": "Credenciales inválidas.", "nav_mode": "auth"})

    request.session["user"] = {"id": user["id"]}
    return RedirectResponse(url="/merchant/dashboard", status_code=303)


@app.get("/auth/merchant/register")
def merchant_register_page(request: Request):
    request.session.clear()
    return tpl(request, "auth_merchant_register.html", {"error": None, "nav_mode": "auth"})


@app.post("/auth/merchant/register")
def merchant_register(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    business_name: str = Form(...),
    route: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    consent: str = Form(""),
):
    v = validate_common_user_fields(full_name, email, phone)
    if isinstance(v, str):
        return tpl(request, "auth_merchant_register.html", {"error": v, "nav_mode": "auth"})
    full_name, email_norm, phone = v

    business_name = _clean(business_name)
    if len(business_name) < 2 or len(business_name) > 80:
        return tpl(request, "auth_merchant_register.html", {"error": "Nombre de negocio inválido (2-80).", "nav_mode": "auth"})

    route = _clean(route)
    if not route:
        return tpl(request, "auth_merchant_register.html", {"error": "Selecciona una ruta.", "nav_mode": "auth"})

    pw_err = validate_password_pair(password, confirm_password)
    if pw_err:
        return tpl(request, "auth_merchant_register.html", {"error": pw_err, "nav_mode": "auth"})

    if not consent:
        return tpl(request, "auth_merchant_register.html", {"error": "Debes aceptar el consentimiento.", "nav_mode": "auth"})

    db = _db()
    if any(normalize_email(u.get("email", "")) == email_norm for u in db["users"]):
        other = email_exists_with_other_role(db["users"], email_norm, "merchant")
        if other:
            return tpl(request, "auth_merchant_register.html", {
                "error": "Ese email ya está registrado como TURISTA. Usa otro email o entra como turista.",
                "nav_mode": "auth",
            })
        return tpl(request, "auth_merchant_register.html", {"error": "Ese email ya existe. Inicia sesión.", "nav_mode": "auth"})

    user_id = new_id("u")
    db["users"].append({
        "id": user_id,
        "role": "merchant",
        "full_name": full_name,
        "email": email_norm,
        "phone": phone,
        "country": "",
        "password_hash": pwd.hash(password),
        "created_at": int(time.time()),
    })
    _save(db)

    request.session["prefill_business"] = {"name": business_name, "route": route}
    request.session["user"] = {"id": user_id}
    return RedirectResponse(url="/merchant/onboarding", status_code=303)


@app.get("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/start", status_code=303)


# -------------------------
# Listings (con roles)
# -------------------------
def can_manage_listing(u: dict, listing: dict) -> bool:
    if not u or (u.get("role") != "merchant"):
        return False
    owner = (listing.get("owner_user_id") or "").strip()
    return (not owner) or (owner == u.get("id"))


@app.get("/listings")
def list_listings(request: Request, route: str = "", category: str = "", q: str = ""):
    u = require_auth(request)
    db = _db()
    listings = db.get("listings", [])

    def ok(item: dict) -> bool:
        if route and (item.get("route", "") or "").lower() != route.lower():
            return False
        if category and (item.get("category", "") or "").lower() != category.lower():
            return False
        if q:
            hay = ((item.get("title", "") or "") + " " + (item.get("short_desc", "") or "")).lower()
            if q.lower() not in hay:
                return False
        return True

    filtered = [l for l in listings if ok(l)]

    return tpl(request, "listings.html", {
        "listings": filtered,
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "route": route,
        "category": category,
        "q": q,
        "nav_mode": "app",
        "user": u,
    })


# -------------------------
# MAPA PUBLICO (NUEVO /map)
# -------------------------
def _haversine_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    R = 6371.0
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    dlat = math.radians(b_lat - a_lat)
    dlng = math.radians(b_lng - a_lng)
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))
    return R * c


def _greedy_path(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= 1:
        return points
    ordered = [points[0]]
    remaining = points[1:]
    while remaining:
        last = ordered[-1]
        best_i = 0
        best_d = 10**18
        for i, p in enumerate(remaining):
            d = _haversine_km(last[0], last[1], p[0], p[1])
            if d < best_d:
                best_d = d
                best_i = i
        ordered.append(remaining.pop(best_i))
    return ordered


@app.get("/map")
def map_page(request: Request, route: str = ""):
    u = require_auth(request)
    db = _db()

    selected_route = (route or "").strip()
    businesses = db.get("businesses", []) or []

    markers = []
    for b in businesses:
        r = (b.get("route") or "").strip()
        if selected_route and r != selected_route:
            continue

        try:
            lat = float(b.get("lat"))
            lng = float(b.get("lng"))
        except Exception:
            continue

        markers.append({
            "id": b.get("id", ""),
            "name": (b.get("name") or "Negocio").strip(),
            "route": r,
            "address": (b.get("address") or "").strip(),
            "maps_url": (b.get("maps_url") or "").strip(),
            "tiktok_url": (b.get("tiktok_url") or "").strip(),
            "phone_whatsapp": (b.get("phone_whatsapp") or b.get("whatsapp") or "").strip(),
            "status": (b.get("status") or "active").strip(),
            "lat": lat,
            "lng": lng,
        })

    path = _greedy_path([[m["lat"], m["lng"]] for m in markers])

    return tpl(request, "map.html", {
        "routes": get_routes(db),
        "selected_route": selected_route,
        "markers_count": len(markers),
        "markers_json": json.dumps(markers, ensure_ascii=False),
        "path_json": json.dumps(path, ensure_ascii=False),
        "nav_mode": "app",
        "user": u,
    })


@app.get("/listings/new")
def new_listing_form(request: Request):
    u = require_auth(request)
    require_role(u, "merchant")
    return tpl(request, "listing_form.html", {"mode": "create", "listing": None, "nav_mode": "app", "user": u})


@app.post("/listings")
def create_listing(
    request: Request,
    route: str = Form(...),
    category: str = Form(...),
    title: str = Form(...),
    short_desc: str = Form(...),
    price_usd: float = Form(...),
    duration_min: int = Form(...),
    address: str = Form(...),
    maps_url: str = Form(""),
    contact_whatsapp: str = Form(""),
    tiktok_url: str = Form(""),
    tags: str = Form(""),
):
    u = require_auth(request)
    require_role(u, "merchant")

    db = _db()
    listing_id = new_id("l")
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]

    listing = {
        "id": listing_id,
        "route": _clean(route),
        "category": _clean(category),
        "title": _clean(title),
        "short_desc": _clean(short_desc),
        "price_usd": float(price_usd),
        "duration_min": int(duration_min),
        "address": _clean(address),
        "maps_url": _clean(maps_url),
        "contact_whatsapp": _clean(contact_whatsapp),
        "tiktok_url": _clean(tiktok_url),
        "tags": tag_list,
        "owner_user_id": u.get("id", ""),
        "created_at": int(time.time()),
    }

    db["listings"].append(listing)
    _save(db)
    return RedirectResponse(url=f"/listings/{listing_id}", status_code=303)


@app.get("/listings/{listing_id}")
def listing_detail(request: Request, listing_id: str):
    u = require_auth(request)
    db = _db()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    return tpl(request, "listing_detail.html", {
        "listing": listing,
        "can_manage": can_manage_listing(u, listing),
        "nav_mode": "app",
        "user": u,
    })


@app.get("/listings/{listing_id}/edit")
def edit_listing_form(request: Request, listing_id: str):
    u = require_auth(request)
    db = _db()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")
    if not can_manage_listing(u, listing):
        raise HTTPException(403, "No autorizado")

    listing = dict(listing)
    listing["tags_str"] = ", ".join(listing.get("tags", []))
    return tpl(request, "listing_form.html", {"mode": "edit", "listing": listing, "nav_mode": "app", "user": u})


@app.post("/listings/{listing_id}/update")
def update_listing(
    request: Request,
    listing_id: str,
    route: str = Form(...),
    category: str = Form(...),
    title: str = Form(...),
    short_desc: str = Form(...),
    price_usd: float = Form(...),
    duration_min: int = Form(...),
    address: str = Form(...),
    maps_url: str = Form(""),
    contact_whatsapp: str = Form(""),
    tiktok_url: str = Form(""),
    tags: str = Form(""),
):
    u = require_auth(request)
    db = _db()
    idx = find_index_by_id(db.get("listings", []), listing_id)
    if idx is None:
        raise HTTPException(404, "Listing no encontrado")

    if not can_manage_listing(u, db["listings"][idx]):
        raise HTTPException(403, "No autorizado")

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]

    db["listings"][idx].update({
        "route": _clean(route),
        "category": _clean(category),
        "title": _clean(title),
        "short_desc": _clean(short_desc),
        "price_usd": float(price_usd),
        "duration_min": int(duration_min),
        "address": _clean(address),
        "maps_url": _clean(maps_url),
        "contact_whatsapp": _clean(contact_whatsapp),
        "tiktok_url": _clean(tiktok_url),
        "tags": tag_list,
    })

    _save(db)
    return RedirectResponse(url=f"/listings/{listing_id}", status_code=303)


@app.post("/listings/{listing_id}/delete")
def delete_listing(request: Request, listing_id: str):
    u = require_auth(request)
    db = _db()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")
    if not can_manage_listing(u, listing):
        raise HTTPException(403, "No autorizado")

    db["listings"] = [l for l in db.get("listings", []) if l.get("id") != listing_id]
    _save(db)
    return RedirectResponse(url="/listings", status_code=303)


# -------------------------
# Merchant dashboard + onboarding
# -------------------------
@app.get("/merchant/dashboard")
def merchant_dashboard(request: Request):
    u = require_auth(request)
    require_role(u, "merchant")

    db = _db()
    biz = find_business_by_owner(db.get("businesses", []), u["id"])
    my_listings = [l for l in db.get("listings", []) if (l.get("owner_user_id") or "") == u["id"]]
    my_listing_ids = {l.get("id") for l in my_listings}
    my_bookings = [bk for bk in db.get("bookings", []) if bk.get("listing_id") in my_listing_ids]

    return tpl(request, "merchant_dashboard.html", {
        "business": biz,
        "business_json": json.dumps(biz or {}, ensure_ascii=False),  # FIX para mapa del dashboard
        "my_listings": my_listings,
        "my_bookings": my_bookings,
        "nav_mode": "app",
        "user": u,
    })


@app.get("/merchant/onboarding")
def merchant_onboarding_page(request: Request):
    u = require_auth(request)
    require_role(u, "merchant")

    pre = request.session.get("prefill_business") or {}
    prefill_name = (pre.get("name") or "").strip()
    prefill_route = (pre.get("route") or "").strip()

    return tpl(request, "merchant_onboarding.html", {
        "error": None,
        "prefill_name": prefill_name,
        "prefill_route": prefill_route or "Cuenca",
        "default_lat": -1.8312,
        "default_lng": -78.1834,
        "nav_mode": "app",
        "user": u,
    })


@app.post("/merchant/onboarding")
def merchant_onboarding_save(
    request: Request,
    name: str = Form(...),
    route: str = Form(...),
    description: str = Form(""),
    address: str = Form(...),
    phone_whatsapp: str = Form(""),
    maps_url: str = Form(""),
    tiktok_url: str = Form(""),
    lat: str = Form(...),
    lng: str = Form(...),
):
    u = require_auth(request)
    require_role(u, "merchant")

    name = _clean(name)
    route = _clean(route)
    description = _clean(description)
    address = _clean(address)
    phone_whatsapp = _clean(phone_whatsapp)
    maps_url = _clean(maps_url)
    tiktok_url = _clean(tiktok_url)

    if len(name) < 2 or len(name) > 80:
        return tpl(request, "merchant_onboarding.html", {
            "error": "Nombre de negocio inválido (2-80).",
            "default_lat": -1.8312, "default_lng": -78.1834,
            "prefill_name": name, "prefill_route": route or "Cuenca",
            "nav_mode": "app", "user": u,
        })

    if len(address) < 3 or len(address) > 140:
        return tpl(request, "merchant_onboarding.html", {
            "error": "Dirección inválida (3-140).",
            "default_lat": -1.8312, "default_lng": -78.1834,
            "prefill_name": name, "prefill_route": route or "Cuenca",
            "nav_mode": "app", "user": u,
        })

    if phone_whatsapp:
        digits = _digits_phone(phone_whatsapp)
        if len(digits) < 8 or len(digits) > 15:
            return tpl(request, "merchant_onboarding.html", {
                "error": "WhatsApp inválido (8-15 dígitos).",
                "default_lat": -1.8312, "default_lng": -78.1834,
                "prefill_name": name, "prefill_route": route or "Cuenca",
                "nav_mode": "app", "user": u,
            })

    if not _valid_url(maps_url):
        return tpl(request, "merchant_onboarding.html", {
            "error": "Maps URL inválida (usa http/https).",
            "default_lat": -1.8312, "default_lng": -78.1834,
            "prefill_name": name, "prefill_route": route or "Cuenca",
            "nav_mode": "app", "user": u,
        })

    if not _valid_url(tiktok_url):
        return tpl(request, "merchant_onboarding.html", {
            "error": "TikTok URL inválida (usa http/https).",
            "default_lat": -1.8312, "default_lng": -78.1834,
            "prefill_name": name, "prefill_route": route or "Cuenca",
            "nav_mode": "app", "user": u,
        })

    try:
        lat_f = float(lat)
        lng_f = float(lng)
        if not (-90 <= lat_f <= 90) or not (-180 <= lng_f <= 180):
            raise ValueError("out of range")
    except Exception:
        return tpl(request, "merchant_onboarding.html", {
            "error": "Ubicación inválida. Coloca el pin en el mapa.",
            "default_lat": -1.8312, "default_lng": -78.1834,
            "prefill_name": name, "prefill_route": route or "Cuenca",
            "nav_mode": "app", "user": u,
        })

    db = _db()
    existing = find_business_by_owner(db.get("businesses", []), u["id"])
    biz_id = existing.get("id") if existing else new_id("biz")

    biz = {
        "id": biz_id,
        "owner_user_id": u["id"],
        "name": name,
        "route": route,
        "description": description,
        "address": address,
        "phone_whatsapp": phone_whatsapp,
        "maps_url": maps_url,
        "tiktok_url": tiktok_url,
        "lat": lat_f,
        "lng": lng_f,
        "status": "active",
        "updated_at": int(time.time()),
    }

    if existing:
        for i, b in enumerate(db["businesses"]):
            if b.get("id") == biz_id:
                db["businesses"][i] = biz
                break
    else:
        db["businesses"].append(biz)

    _save(db)
    request.session.pop("prefill_business", None)
    return RedirectResponse(url="/merchant/dashboard", status_code=303)


# -------------------------
# ASSISTANT
# -------------------------
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

ITINERARY_SCHEMA = {
    "name": "itinerary_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "route": {"type": "string"},
            "days": {"type": "integer"},
            "budget": {"type": "number"},
            "estimate_total": {"type": "number"},
            "estimate_per_person": {"type": "number"},
            "party_size": {"type": "integer"},
            "language": {"type": "string"},
            "package_name": {"type": "string"},
            "narrative": {"type": "string"},
            "plan_b": {"type": "array", "items": {"type": "string"}},
            "sustainability": {"type": "array", "items": {"type": "string"}},
            "itinerary": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "day": {"type": "integer"},
                        "day_theme": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "listing_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "category": {"type": "string"},
                                    "why": {"type": "string"},
                                    "price_usd": {"type": "number"},
                                    "duration_min": {"type": "integer"},
                                    "address": {"type": "string"},
                                    "maps_url": {"type": ["string", "null"]},
                                    "tiktok_url": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "listing_id", "title", "category", "why",
                                    "price_usd", "duration_min", "address",
                                    "maps_url", "tiktok_url"
                                ],
                            },
                        },
                    },
                    "required": ["day", "day_theme", "items"],
                },
            },
        },
        "required": [
            "route", "days", "budget",
            "estimate_total", "estimate_per_person",
            "party_size", "language", "package_name",
            "narrative", "plan_b", "sustainability", "itinerary"
        ],
    },
    "strict": True,
}


def _extract_output_text(resp_json: dict) -> str:
    chunks = []
    for item in resp_json.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                chunks.append(c.get("text", ""))
    return "\n".join(chunks).strip()


def _parse_json_from_text(txt: str) -> dict:
    txt = (txt or "").strip()
    if not txt:
        raise ValueError("Respuesta vacía del modelo (sin output_text).")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(txt[start:end + 1])
        raise


def _safe_int(x: Any, d: int) -> int:
    try:
        return int(x)
    except Exception:
        return d


def _safe_float(x: Any, d: float) -> float:
    try:
        return float(x)
    except Exception:
        return d


def _recalc_per_person(itinerary: list[dict]) -> float:
    total = 0.0
    for day in itinerary or []:
        for it in (day.get("items") or []):
            total += _safe_float(it.get("price_usd"), 0.0)
    return round(total, 2)


def generate_itinerary_with_openai(
    route: str,
    days: int,
    budget_per_person: float,
    interests: list[str],
    candidates: list[dict],
    party_size: int,
    language_pref: str,
) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env/env")

    model = os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"

    # Para 7 días: reduce items/día para no reventar JSON
    max_items_per_day = 4 if days <= 3 else 3

    slim = []
    for l in (candidates or [])[:60]:
        slim.append({
            "id": l.get("id", ""),
            "title": l.get("title", ""),
            "category": (l.get("category") or "").strip().lower(),
            "short_desc": l.get("short_desc", "") or "",
            "price_usd": _safe_float(l.get("price_usd", 0), 0.0),
            "duration_min": _safe_int(l.get("duration_min", 60), 60),
            "address": l.get("address", "") or "",
            "maps_url": (l.get("maps_url") or None) if str(l.get("maps_url") or "").strip() else None,
            "tiktok_url": (l.get("tiktok_url") or None) if str(l.get("tiktok_url") or "").strip() else None,
            "tags": l.get("tags", []) or [],
        })

    system = (
        "Eres un asistente para planificar rutas culturales sostenibles en Ecuador.\n"
        "REGLAS DURAS:\n"
        "1) NO inventes lugares.\n"
        "2) SOLO usa listing_id de los candidatos.\n"
        f"3) Máximo {max_items_per_day} items por día.\n"
        "4) Devuelve SOLO JSON válido. Nada de texto extra.\n"
        "5) narrative corto (<=220 chars). plan_b y sustainability máximo 3 bullets.\n"
        "6) budget es por persona. estimate_total = estimate_per_person * party_size.\n"
    )

    user = {
        "route": route,
        "days": days,
        "party_size": party_size,
        "budget_usd_per_person": budget_per_person,
        "user_language": language_pref,
        "interests_categories": interests,
        "candidates": slim,
        "constraints": {"max_items_per_day": max_items_per_day},
    }

    base_tokens = 3200 if days <= 3 else 5200

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": ITINERARY_SCHEMA["name"],
                "schema": ITINERARY_SCHEMA["schema"],
                "strict": True,
            }
        },
        "store": False,
        "max_output_tokens": base_tokens,
        "temperature": 0.2,
        "top_p": 1,
    }

    r = requests.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=45,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {r.status_code}: {r.text[:500]}")

    resp = r.json()
    if str(resp.get("status", "")).lower() == "incomplete":
        raise RuntimeError("OpenAI devolvió respuesta INCOMPLETA (sube max_output_tokens o reduce salida).")

    txt = _extract_output_text(resp)
    try:
        return _parse_json_from_text(txt)
    except json.JSONDecodeError:
        payload["max_output_tokens"] = 6500
        payload["input"][0]["content"] = system + "\nMÁS CORTO. JSON PURO. Sin texto adicional."
        r2 = requests.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=45,
        )
        if r2.status_code >= 400:
            raise RuntimeError(f"OpenAI retry error {r2.status_code}: {r2.text[:500]}")
        resp2 = r2.json()
        if str(resp2.get("status", "")).lower() == "incomplete":
            raise RuntimeError("OpenAI retry devolvió respuesta INCOMPLETA.")
        txt2 = _extract_output_text(resp2)
        return _parse_json_from_text(txt2)


@app.get("/assistant")
def assistant_page(request: Request):
    u = require_auth(request)
    db = _db()
    return tpl(request, "assistant.html", {
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "result": None,
        "form": None,
        "ai_error": None,
        "nav_mode": "app",
        "user": u,
    })


@app.post("/assistant")
def assistant_generate(
    request: Request,
    route: str = Form(...),
    days: int = Form(2),
    budget: float = Form(60),
    interests: list[str] = Form([]),
    party_size: int = Form(2),
    language_pref: str = Form("ES/EN"),
):
    u = require_auth(request)
    db = _db()

    route_clean = (route or "").strip()

    all_listings = db.get("listings", []) or []
    if route_clean.lower() == "ecuador":
        listings = all_listings
    else:
        listings = [l for l in all_listings if (l.get("route") or "").strip() == route_clean]

    days = max(1, min(int(days), 7))
    budget = float(budget)
    interests = interests or []
    party_size = max(1, min(int(party_size), 10))
    language_pref = (language_pref or "ES/EN").strip()

    ai_error = None

    try:
        result = generate_itinerary_with_openai(
            route=route_clean,
            days=days,
            budget_per_person=budget,
            interests=interests,
            candidates=listings,
            party_size=party_size,
            language_pref=language_pref,
        )

        listing_map = {l.get("id"): l for l in listings if l.get("id")}
        valid_ids = set(listing_map.keys())

        clean_days = []
        for day in result.get("itinerary", []) or []:
            items_ok = []
            for it in (day.get("items") or []):
                lid = it.get("listing_id")
                if lid not in valid_ids:
                    continue
                src = listing_map[lid]
                it["title"] = (it.get("title") or src.get("title") or "Experiencia").strip()
                it["category"] = (it.get("category") or src.get("category") or "").strip().lower() or "comida"
                it["price_usd"] = _safe_float(it.get("price_usd"), _safe_float(src.get("price_usd"), 0.0))
                it["duration_min"] = _safe_int(it.get("duration_min"), _safe_int(src.get("duration_min"), 60))
                it["address"] = (it.get("address") or src.get("address") or "-").strip()
                it["maps_url"] = it.get("maps_url") or (src.get("maps_url") or None)
                it["tiktok_url"] = it.get("tiktok_url") or (src.get("tiktok_url") or None)
                items_ok.append(it)

            clean_days.append({
                "day": _safe_int(day.get("day"), 1),
                "day_theme": (day.get("day_theme") or "Ruta cultural optimizada").strip(),
                "items": items_ok
            })

        result["itinerary"] = clean_days

        per_person = _recalc_per_person(result.get("itinerary") or [])
        result["estimate_per_person"] = per_person
        result["estimate_total"] = round(per_person * party_size, 2)
        result["party_size"] = party_size
        result["language"] = result.get("language") or language_pref
        result["package_name"] = result.get("package_name") or f"Ruta Cultural: {route_clean}"

        if not result.get("plan_b"):
            result["plan_b"] = ["Si llueve: prioriza museos/talleres.", "Si está lleno: cambia a un spot similar.", "Reduce 1 item por día."]
        if not result.get("sustainability"):
            result["sustainability"] = ["Compra local.", "Respeta cultura: pide permiso antes de grabar.", "Evita saturar sitios pequeños."]
        if not result.get("narrative"):
            result["narrative"] = "Itinerario diseñado para maximizar cultura y economía local."

    except Exception as e:
        ai_error = str(e)

        random.shuffle(listings)
        itinerary = []
        budget_left = budget

        max_items = 4 if days <= 3 else 3

        def pick(pool, interests_list, budget_left_val, max_items=3):
            if interests_list:
                filtered = [p for p in pool if (p.get("category") or "").strip().lower() in [x.lower() for x in interests_list]]
                if filtered:
                    pool = filtered
            pool = sorted(pool, key=lambda x: float(x.get("price_usd", 0) or 0))
            picked, total = [], 0.0
            for item in pool:
                if len(picked) >= max_items:
                    break
                price = float(item.get("price_usd", 0) or 0)
                if total + price <= budget_left_val:
                    picked.append(item)
                    total += price
            return picked, total

        for d in range(1, days + 1):
            day_items, day_total = pick(listings, interests, budget_left, max_items)
            budget_left = max(0.0, budget_left - day_total)
            itinerary.append({
                "day": d,
                "day_theme": "Selección por presupuesto",
                "items": [
                    {
                        "listing_id": it.get("id"),
                        "title": it.get("title"),
                        "category": (it.get("category") or "").strip().lower(),
                        "why": "Fallback sin IA: selección por presupuesto + categoría.",
                        "price_usd": float(it.get("price_usd", 0) or 0),
                        "duration_min": int(it.get("duration_min", 60) or 60),
                        "address": it.get("address", "") or "",
                        "maps_url": it.get("maps_url") or None,
                        "tiktok_url": it.get("tiktok_url") or None,
                    } for it in day_items
                ]
            })

        per_person = _recalc_per_person(itinerary)

        result = {
            "route": route_clean,
            "days": days,
            "budget": budget,
            "estimate_per_person": per_person,
            "estimate_total": round(per_person * party_size, 2),
            "party_size": party_size,
            "language": language_pref,
            "package_name": f"Ruta Cultural: {route_clean}",
            "narrative": "La IA falló y el sistema usó fallback.",
            "plan_b": ["Si llueve: museos/talleres bajo techo.", "Si está lleno: cambia por otro similar.", "Baja días o presupuesto."],
            "sustainability": ["Compra local y respeta cultura."],
            "itinerary": itinerary,
        }

    form_state = {
        "route": route_clean,
        "days": days,
        "budget": budget,
        "interests": interests,
        "party_size": party_size,
        "language_pref": language_pref,
    }

    return tpl(request, "assistant.html", {
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "result": result,
        "form": form_state,
        "ai_error": ai_error,
        "nav_mode": "app",
        "user": u,
    })


# -------------------------
# PayPal checkout (solo turista)
# -------------------------
@app.get("/listings/{listing_id}/book")
def book_listing(request: Request, listing_id: str):
    u = require_auth(request)
    require_role(u, "tourist")

    db = _db()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    env = os.getenv("PAYPAL_ENV", "sandbox")

    return tpl(request, "booking_checkout.html", {
        "listing": listing,
        "paypal_client_id": get_client_id(),
        "env": env,
        "nav_mode": "app",
        "user": u,
    })


@app.post("/paypal/create-order")
def paypal_create_order(payload: dict = Body(...), request: Request = None):
    u = require_auth(request)
    require_role(u, "tourist")
    return create_order(payload)


@app.post("/paypal/capture-order")
def paypal_capture_order(payload: dict = Body(...), request: Request = None):
    u = require_auth(request)
    require_role(u, "tourist")
    return capture_order(payload)
