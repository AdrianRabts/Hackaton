from typing import List, Optional
from pydantic import BaseModel, Field


# ====== LISTINGS ======
class Listing(BaseModel):
    id: str
    route: str = Field(min_length=1)
    category: str = Field(min_length=1)  # comida | historico | parque | artesania
    title: str = Field(min_length=1)
    short_desc: str = Field(min_length=1)

    price_usd: float = Field(default=0.0, ge=0)
    duration_min: int = Field(default=0, ge=0)

    address: str = Field(min_length=1)

    maps_url: Optional[str] = ""
    contact_whatsapp: Optional[str] = ""
    tiktok_url: Optional[str] = ""

    tags: List[str] = []


# ====== BOOKINGS ======
class Booking(BaseModel):
    id: str
    listing_id: str = Field(min_length=1)

    buyer_name: str = Field(default="Guest", min_length=1)
    buyer_email: str = Field(default="guest@example.com", min_length=3)

    amount_usd: float = Field(default=0.0, ge=0)
    paypal_order_id: str = Field(min_length=1)

    # CREATED | PAID | FAILED (MVP)
    status: str = Field(default="CREATED")
