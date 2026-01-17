from typing import List, Optional
from pydantic import BaseModel, Field

class Listing(BaseModel):
    id: str
    route: str
    category: str  # comida | historico | parque | artesania
    title: str
    short_desc: str
    price_usd: float = Field(ge=0)
    duration_min: int = Field(ge=0)
    address: str
    maps_url: Optional[str] = ""
    contact_whatsapp: Optional[str] = ""
    tiktok_url: Optional[str] = ""
    tags: List[str] = []

class ListingCreate(BaseModel):
    route: str
    category: str
    title: str
    short_desc: str
    price_usd: float = Field(ge=0)
    duration_min: int = Field(ge=0)
    address: str
    maps_url: Optional[str] = ""
    contact_whatsapp: Optional[str] = ""
    tiktok_url: Optional[str] = ""
    tags: str = ""  # comma-separated en el form

class Booking(BaseModel):
    id: str
    listing_id: str
    buyer_name: str
    buyer_email: str
    amount_usd: float
    paypal_order_id: str
    status: str  # CREATED | PAID | FAILED
