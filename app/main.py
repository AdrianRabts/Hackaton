import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import JsonStore, new_id
from app.models import Listing, Booking
from app.paypal import create_order, capture_order, get_client_id

# Cargar .env simple (sin dependencia extra)
def load_env():
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()

app = FastAPI(title="Cultural Routes MVP")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
store = JsonStore()

@app.get("/")
def home():
    return RedirectResponse(url="/listings", status_code=302)

@app.get("/listings")
def list_listings(request: Request, route: str = "", category: str = "", q: str = ""):
    db = store.read()
    listings = db["listings"]

    def ok(item):
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
    routes = sorted({l["route"] for l in listings}) if listings else ["Cuenca", "Tena", "Ruta Spondylus / Montañita"]
    categories = ["comida", "historico", "parque", "artesania"]

    return templates.TemplateResponse("listings.html", {
        "request": request,
        "listings": filtered,
        "route": route,
        "category": category,
        "q": q,
        "routes": routes,
        "categories": categories
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
        price_usd=price_usd,
        duration_min=duration_min,
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
    listing = next((l for l in db["listings"] if l["id"] == listing_id), None)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    return templates.TemplateResponse("listing_detail.html", {
        "request": request,
        "listing": listing
    })

@app.get("/listings/{listing_id}/edit")
def edit_listing_form(request: Request, listing_id: str):
    db = store.read()
    listing = next((l for l in db["listings"] if l["id"] == listing_id), None)
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
    idx = next((i for i, l in enumerate(db["listings"]) if l["id"] == listing_id), None)
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
    db["listings"] = [l for l in db["listings"] if l["id"] != listing_id]
    store.write(db)
    return RedirectResponse(url="/listings", status_code=303)

# Checkout page
@app.get("/listings/{listing_id}/book")
def book_listing(request: Request, listing_id: str):
    db = store.read()
    listing = next((l for l in db["listings"] if l["id"] == listing_id), None)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    return templates.TemplateResponse("booking_checkout.html", {
        "request": request,
        "listing": listing,
        "paypal_client_id": get_client_id()
    })

# PayPal API endpoints
@app.post("/api/paypal/create-order")
async def api_create_order(payload: dict):
    listing_id = payload.get("listing_id", "")
    db = store.read()
    listing = next((l for l in db["listings"] if l["id"] == listing_id), None)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    amount = float(listing["price_usd"])
    order = create_order(amount_usd=amount, reference_id=listing_id)
    return JSONResponse({"order_id": order.get("id")})

@app.post("/api/paypal/capture-order")
async def api_capture_order(payload: dict):
    listing_id = payload.get("listing_id", "")
    order_id = payload.get("order_id", "")

    if not listing_id or not order_id:
        raise HTTPException(400, "Faltan listing_id u order_id")

    db = store.read()
    listing = next((l for l in db["listings"] if l["id"] == listing_id), None)
    if not listing:
        raise HTTPException(404, "Listing no encontrado")

    try:
        result = capture_order(order_id)
        status = result.get("status", "UNKNOWN")
        paid = status.upper() == "COMPLETED"
    except Exception as e:
        paid = False
        status = "FAILED"

    booking_id = new_id("b")
    booking = Booking(
        id=booking_id,
        listing_id=listing_id,
        buyer_name=payload.get("buyer_name", "Guest"),
        buyer_email=payload.get("buyer_email", "guest@example.com"),
        amount_usd=float(listing["price_usd"]),
        paypal_order_id=order_id,
        status="PAID" if paid else "FAILED"
    ).model_dump()

    db["bookings"].append(booking)
    store.write(db)

    return JSONResponse({
        "ok": paid,
        "paypal_status": status,
        "booking_id": booking_id
    })
