from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class Location(BaseModel):
    lat: float
    lon: float


class RawOffer(BaseModel):
    """What an adapter returns. Unprocessed, straight from the store."""
    store: str
    store_name: str
    title: str
    price: float                       # rupees, what you actually pay
    mrp: Optional[float] = None        # struck-through price, if shown
    in_stock: bool = True
    quantity_text: Optional[str] = None   # some stores give this separately
    image_url: Optional[str] = None
    deeplink: Optional[str] = None
    store_product_id: Optional[str] = None


class Offer(BaseModel):
    """A RawOffer after normalization. This is what the app sees."""
    store: str
    store_name: str
    title: str
    price: float
    mrp: Optional[float] = None
    discount_pct: Optional[int] = None
    in_stock: bool = True
    image_url: Optional[str] = None
    deeplink: Optional[str] = None

    # normalized facts
    brand: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None            # display unit: ml, g, l, kg, pc
    base_quantity: Optional[float] = None  # always in ml, g or pc
    base_unit: Optional[str] = None
    price_per_100: Optional[float] = None  # ₹ per 100ml / 100g / per piece


class ProductRow(BaseModel):
    """One line in the app: a product, and every store that has it."""
    display_name: str
    brand: Optional[str] = None
    quantity_label: Optional[str] = None   # "500 ml"
    image_url: Optional[str] = None
    offers: list[Offer]                    # sorted, cheapest first
    best_price: float
    best_store: str
    max_saving: float = 0.0                # vs the priciest in-stock offer
    stores_available: int = 0


class SearchResponse(BaseModel):
    query: str
    location: Location
    products: list[ProductRow]
    stores_queried: list[str] = Field(default_factory=list)
    stores_degraded: list[str] = Field(default_factory=list)  # failed or empty
    cached_stores: list[str] = Field(default_factory=list)
    took_ms: int = 0
