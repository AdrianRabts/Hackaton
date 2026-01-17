import os
import random
from typing import Any

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import JsonStore, new_id, find_by_id, find_index_by_id
from app.models import Listing, Booking
from app.paypal import create_order, capture_order, get_client_id


# ====== ENV LOADER (sin librerías extra) ======
def load_env() -> None:
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()


# ====== APP ======
app = FastAPI(title="Cultural Routes MVP")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
store = JsonStore()

CATEGORIES = ["comida", "historico", "parque", "artesania"]


# ====== UTIL ======
def get_routes(db: dict) -> list[str]:
    listings = db.get("listings", [])
    routes = sorted({l.get("route", "") for l in listings if l.get("route")})
    return routes or ["Ruta Spondylus / Montañita", "Cuenca", "Tena"]


# ====== BASIC ======
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)

@app.get("/")
def home():
    return RedirectResponse(url="/listings", status_code=302)


# ====== LISTINGS (CRUD) ======
@app.get("/listings")
def list_listings(request: Request, route: str = "", category: str = "", q: str = ""):
    db = store.read()
    listings = db.get("listings", [])

    def ok(item: dict) -> bool:
        if route and item.get("route", "").lower() != route.lower():
            return False
        if category and item.get("category", "").lower() != category.lower():
            return False
        if q:
            hay = (item.get("title", "") + " " + item.get("short_desc", "")).lower()
            if q.lower() not in hay:
                return False
        return True

    filtered = [l for l in listings if ok(l)]

    return templates.TemplateResponse("listings.html", {
        "request": request,
        "listings": filtered,
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "route": route,
        "category": category,
        "q": q
    })


@app.get("/listings/new")
def new_listing_form(request: Request):
    return templates.TemplateResponse("listing_form.html", {"request": request, "mode": "create", "listing": None})


@app.post("/listings")
def create_listing(
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
    tags: str = Form("")
):
    db = store.read()
    listing_id = new_id("l")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    listing = Listing(
        id=listing_id,
        route=route,
        category=category,
        title=title,
        short_desc=short_desc,
        price_usd=float(price_usd),
        duration_min=int(duration_min),
        address=address,
        maps_url=maps_url,
        contact_whatsapp=contact_whatsapp,
        tiktok_url=tiktok_url,
        tags=tag_list
    ).model_dump()

    db["listings"].append(listing)
    store.write(db)
    return RedirectResponse(url=f"/listings/{listing_id}", status_code=303)


@app.get("/listings/{listing_id}")
def listing_detail(request: Request, listing_id: str):
    db = store.read()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    return templates.TemplateResponse("listing_detail.html", {"request": request, "listing": listing})


@app.get("/listings/{listing_id}/edit")
def edit_listing_form(request: Request, listing_id: str):
    db = store.read()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    listing = dict(listing)
    listing["tags_str"] = ", ".join(listing.get("tags", []))
    return templates.TemplateResponse("listing_form.html", {"request": request, "mode": "edit", "listing": listing})


@app.post("/listings/{listing_id}/update")
def update_listing(
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
    tags: str = Form("")
):
    db = store.read()
    idx = find_index_by_id(db.get("listings", []), listing_id)
    if idx is None:
        raise HTTPException(404, "Listing no encontrado")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    db["listings"][idx].update({
        "route": route,
        "category": category,
        "title": title,
        "short_desc": short_desc,
        "price_usd": float(price_usd),
        "duration_min": int(duration_min),
        "address": address,
        "maps_url": maps_url,
        "contact_whatsapp": contact_whatsapp,
        "tiktok_url": tiktok_url,
        "tags": tag_list
    })

    store.write(db)
    return RedirectResponse(url=f"/listings/{listing_id}", status_code=303)


@app.post("/listings/{listing_id}/delete")
def delete_listing(listing_id: str):
    db = store.read()
    db["listings"] = [l for l in db.get("listings", []) if l.get("id") != listing_id]
    store.write(db)
    return RedirectResponse(url="/listings", status_code=303)


# ====== ASSISTANT (itinerarios) ======
def build_narrative(item: dict) -> str:
    lines = [
        "Pregunta por la historia del lugar: ahí está el valor cultural, no solo la foto.",
        "Compra local, aunque sea pequeño: eso sí se queda en la comunidad.",
        "Respeta el espacio y la gente: cultura no es parque temático.",
        "Si puedes, anda con guía/host local: sube la experiencia y el impacto."
    ]
    return random.choice(lines)

def pick_items_for_day(pool: list[dict], interests: list[str], budget_left: float, max_items: int = 4):
    if interests:
        filtered = [p for p in pool if p.get("category") in interests]
        if filtered:
            pool = filtered

    pool = sorted(pool, key=lambda x: float(x.get("price_usd", 0)))
    picked = []
    total = 0.0

    for item in pool:
        if len(picked) >= max_items:
            break
        price = float(item.get("price_usd", 0))
        if total + price <= budget_left:
            it = dict(item)
            it["narrative"] = build_narrative(it)
            picked.append(it)
            total += price

    if not picked and pool:
        it = dict(pool[0])
        it["narrative"] = build_narrative(it)
        picked.append(it)
        total = float(it.get("price_usd", 0))

    return picked, total

@app.get("/assistant")
def assistant_page(request: Request):
    db = store.read()
    return templates.TemplateResponse("assistant.html", {
        "request": request,
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "result": None,
        "form": None
    })

@app.post("/assistant")
def assistant_generate(
    request: Request,
    route: str = Form(...),
    days: int = Form(2),
    budget: float = Form(60),
    interests: list[str] = Form([])
):
    db = store.read()
    listings = [l for l in db.get("listings", []) if l.get("route") == route]

    days = max(1, min(int(days), 3))
    budget = float(budget)
    interests = interests or []

    random.shuffle(listings)

    itinerary = []
    estimate_total = 0.0
    budget_left = budget

    for d in range(1, days + 1):
        day_items, day_total = pick_items_for_day(
            pool=listings,
            interests=interests,
            budget_left=budget_left,
            max_items=4
        )
        estimate_total += day_total
        budget_left = max(0.0, budget_left - day_total)

        itinerary.append({"day": d, "items": day_items})

    result = {
        "route": route,
        "days": days,
        "budget": budget,
        "estimate_total": estimate_total,
        "itinerary": itinerary,
        "plan_b": [
            "Si llueve: prioriza museos/talleres bajo techo y mueve parques para otro día.",
            "Si está lleno: cambia por otro lugar de la misma categoría (misma vibra, menos cola).",
            "Si cierran temprano: arranca por lo más lejano y luego te devuelves al centro."
        ],
        "sustainability": [
            "Compra local: comida/arte directo al emprendedor (impacto real).",
            "Pide permiso antes de grabar o fotografiar (respeto cultural).",
            "Evita saturación: horarios alternos y grupos pequeños."
        ]
    }

    form_state = {"route": route, "days": days, "budget": budget, "interests": interests}

    return templates.TemplateResponse("assistant.html", {
        "request": request,
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "result": result,
        "form": form_state
    })


# ====== PAYPAL CHECKOUT ======
@app.get("/listings/{listing_id}/book")
def book_listing(request: Request, listing_id: str):
    db = store.read()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    env = os.getenv("PAYPAL_ENV", "sandbox")

    return templates.TemplateResponse("booking_checkout.html", {
        "request": request,
        "listing": listing,
        "paypal_client_id": get_client_id(),
        "env": env
    })


@app.post("/api/paypal/create-order")
async def api_create_order(payload: dict):
    listing_id = payload.get("listing_id", "")
    db = store.read()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    amount = float(listing.get("price_usd", 0))
    order = create_order(amount_usd=amount, reference_id=listing_id)
    return JSONResponse({"order_id": order.get("id")})


@app.post("/api/paypal/capture-order")
async def api_capture_order(payload: dict):
    listing_id = payload.get("listing_id", "")
    order_id = payload.get("order_id", "")

    if not listing_id or not order_id:
        raise HTTPException(400, "Faltan listing_id u order_id")

    db = store.read()
    listing = find_by_id(db.get("listings", []), listing_id)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    try:
        result = capture_order(order_id)
        status = result.get("status", "UNKNOWN")
        paid = str(status).upper() == "COMPLETED"
    except Exception as e:
        paid = False
        status = "FAILED"

    booking_id = new_id("b")
    booking = Booking(
        id=booking_id,
        listing_id=listing_id,
        buyer_name=payload.get("buyer_name", "Guest"),
        buyer_email=payload.get("buyer_email", "guest@example.com"),
        amount_usd=float(listing.get("price_usd", 0)),
        paypal_order_id=order_id,
        status="PAID" if paid else "FAILED"
    ).model_dump()

    db["bookings"].append(booking)
    store.write(db)

    return JSONResponse({"ok": paid, "paypal_status": status, "booking_id": booking_id})
