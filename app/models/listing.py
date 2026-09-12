from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Availability = Literal["available", "unavailable", "unknown"]
MeasureKind = Literal["mass", "volume", "count", "unknown"]


class RawListing(BaseModel):
    platform: Literal["blinkit", "instamart"]
    provider_id: str | None = None
    title: str
    size_text: str | None = None
    price: Decimal | None = None
    mrp: Decimal | None = None
    offer_text: str | None = None
    image_url: str | None = None
    product_url: str | None = None
    sponsored: bool = False
    availability: Availability = "unknown"
    raw_text: str
    fetched_at: datetime
    attributes: dict[str, str] = Field(default_factory=dict)


class NormalizedProduct(BaseModel):
    raw: RawListing
    normalized_title: str
    title_tokens: list[str]
    brand_hint: str | None = None
    variant_tokens: set[str] = Field(default_factory=set)
    measure_kind: MeasureKind = "unknown"
    item_amount_base: float | None = None
    base_unit: Literal["g", "ml", "pcs"] | None = None
    pack_count: int = 1
    total_amount_base: float | None = None
