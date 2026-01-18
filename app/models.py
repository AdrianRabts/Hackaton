from typing import List, Optional
from pydantic import BaseModel, Field


class Listing(BaseModel):
    id: str
    route: str = Field(min_length=1)
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    short_desc: str = Field(min_length=1)

    price_usd: float = Field(default=0.0, ge=0)
    duration_min: int = Field(default=0, ge=0)

    address: str = Field(min_length=1)

    maps_url: Optional[str] = ""
    contact_whatsapp: Optional[str] = ""
    tiktok_url: Optional[str] = ""

    tags: List[str] = []

    owner_user_id: Optional[str] = ""


class Booking(BaseModel):
    id: str
    listing_id: str = Field(min_length=1)

    buyer_name: str = Field(default="Guest", min_length=1)
    buyer_email: str = Field(default="guest@example.com", min_length=3)

    amount_usd: float = Field(default=0.0, ge=0)
    paypal_order_id: str = Field(min_length=1)

    status: str = Field(default="CREATED")  # CREATED | PAID | FAILED
    user_id: Optional[str] = ""


class User(BaseModel):
    id: str
    role: str = Field(default="tourist")  # tourist | merchant

    full_name: str = Field(min_length=2)
    email: str = Field(min_length=3)
    phone: str = Field(min_length=6)

    country: Optional[str] = ""
    password_hash: str = Field(min_length=10)


class Business(BaseModel):
    id: str
    owner_user_id: str = Field(min_length=1)

    name: str = Field(min_length=2)
    route: str = Field(min_length=1)

    description: Optional[str] = ""
    address: str = Field(min_length=2)

    phone_whatsapp: Optional[str] = ""
    maps_url: Optional[str] = ""
    tiktok_url: Optional[str] = ""

    lat: float
    lng: float

    status: str = Field(default="active")  # active | pending
