
import json
import requests
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


# ====== ASSISTANT (IA real con OpenAI Responses API) ======

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
                                    "maps_url": {"type": "string"},
                                    "tiktok_url": {"type": "string"},
                                },
                                "required": [
                                    "listing_id",
                                    "title",
                                    "category",
                                    "why",
                                    "price_usd",
                                    "duration_min",
                                    "address",
                                ],
                            },
                        },
                    },
                    "required": ["day", "items"],
                },
            },
        },
        "required": [
            "route",
            "days",
            "budget",
            "estimate_total",
            "narrative",
            "plan_b",
            "sustainability",
            "itinerary",
        ],
    },
    "strict": True,
}


def _extract_output_text(resp_json: dict) -> str:
    # En Responses API, la salida viene en resp_json["output"] como items de tipo "message"
    chunks = []
    for item in resp_json.get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                chunks.append(c.get("text", ""))
    return "\n".join(chunks).strip()


def generate_itinerary_with_openai(
    route: str, days: int, budget: float, interests: list[str], candidates: list[dict]
) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env")

    model = os.getenv("OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2"

    # recortamos candidatos para no mandar un libro entero
    slim = []
    for l in candidates[:40]:
        slim.append({
            "id": l.get("id", ""),
            "title": l.get("title", ""),
            "category": l.get("category", ""),
            "short_desc": l.get("short_desc", ""),
            "price_usd": float(l.get("price_usd", 0)),
            "duration_min": int(l.get("duration_min", 0)),
            "address": l.get("address", ""),
            "maps_url": l.get("maps_url", ""),
            "tiktok_url": l.get("tiktok_url", ""),
            "tags": l.get("tags", []),
        })

    system = (
        "Eres un asistente de itinerarios culturales sostenibles en Ecuador. "
        "Tu objetivo: convertir oferta dispersa en un itinerario vendible. "
        "Reglas: NO inventes lugares. SOLO usa listing_id de los candidatos. "
        "Optimiza por: autenticidad cultural, compra local, logística realista, y presupuesto."
    )

    user = {
        "route": route,
        "days": days,
        "budget_usd": budget,
        "interests_categories": interests,
        "candidates": slim,
        "constraints": {
            "max_items_per_day": 4,
            "prefer_mix_categories": True,
            "keep_total_under_budget_if_possible": True
        }
    }

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)}
        ],
        # Structured Outputs en Responses API se define con text.format (json_schema) :contentReference[oaicite:3]{index=3}
        "text": {
            "format": {
                "type": "json_schema",
                "name": ITINERARY_SCHEMA["name"],
                "schema": ITINERARY_SCHEMA["schema"],
                "strict": True,
            }
        },
        # Para hackathon: mejor no almacenar (store por defecto es true) :contentReference[oaicite:4]{index=4}
        "store": False,
        "max_output_tokens": 900
    }

    r = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key}",  # Bearer auth :contentReference[oaicite:5]{index=5}
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=35,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {r.status_code}: {r.text[:300]}")

    resp_json = r.json()
    txt = _extract_output_text(resp_json)
    if not txt:
        raise RuntimeError("OpenAI no devolvió texto")
    return json.loads(txt)


@app.get("/assistant")
def assistant_page(request: Request):
    db = store.read()
    return templates.TemplateResponse("assistant.html", {
        "request": request,
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "result": None,
        "form": None,
        "ai_error": None
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

    ai_error = None

    try:
        result = generate_itinerary_with_openai(
            route=route,
            days=days,
            budget=budget,
            interests=interests,
            candidates=listings
        )

        # Validación rápida: si el modelo inventa un id, lo botamos
        valid_ids = {l.get("id") for l in listings}
        for day in result.get("itinerary", []):
            day["items"] = [it for it in day.get("items", []) if it.get("listing_id") in valid_ids]

    except Exception as e:
        # Fallback: si la IA falla por red o key, no muere el demo
        ai_error = str(e)

        # fallback simple (lo que ya tenías)
        random.shuffle(listings)
        itinerary = []
        estimate_total = 0.0
        budget_left = budget

        def pick(pool, interests, budget_left, max_items=4):
            if interests:
                filtered = [p for p in pool if p.get("category") in interests]
                if filtered:
                    pool = filtered
            pool = sorted(pool, key=lambda x: float(x.get("price_usd", 0)))
            picked, total = [], 0.0
            for item in pool:
                if len(picked) >= max_items:
                    break
                price = float(item.get("price_usd", 0))
                if total + price <= budget_left:
                    picked.append(item)
                    total += price
            return picked, total

        for d in range(1, days + 1):
            day_items, day_total = pick(listings, interests, budget_left, 4)
            estimate_total += day_total
            budget_left = max(0.0, budget_left - day_total)
            itinerary.append({
                "day": d,
                "items": [
                    {
                        "listing_id": it.get("id"),
                        "title": it.get("title"),
                        "category": it.get("category"),
                        "why": "Fallback sin IA: selección por presupuesto + categoría.",
                        "price_usd": float(it.get("price_usd", 0)),
                        "duration_min": int(it.get("duration_min", 0)),
                        "address": it.get("address", ""),
                        "maps_url": it.get("maps_url", ""),
                        "tiktok_url": it.get("tiktok_url", ""),
                    } for it in day_items
                ]
            })

        result = {
            "route": route,
            "days": days,
            "budget": budget,
            "estimate_total": estimate_total,
            "narrative": "Modo fallback: hoy la IA se fue a comprar encebollado, pero el demo sigue vivo.",
            "plan_b": [
                "Si llueve: museos/talleres bajo techo primero.",
                "Si está lleno: cambia por otro de la misma categoría."
            ],
            "sustainability": [
                "Compra local y respeta cultura (no es parque temático)."
            ],
            "itinerary": itinerary
        }

    form_state = {"route": route, "days": days, "budget": budget, "interests": interests}

    return templates.TemplateResponse("assistant.html", {
        "request": request,
        "routes": get_routes(db),
        "categories": CATEGORIES,
        "result": result,
        "form": form_state,
        "ai_error": ai_error
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
