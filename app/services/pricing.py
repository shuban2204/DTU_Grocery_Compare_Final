from __future__ import annotations

import re
from decimal import Decimal

from pydantic import BaseModel

from app.models import NormalizedProduct, RawListing


class OfferRule(BaseModel):
    bundle_qty: int
    bundle_price: Decimal
    source_text: str


def parse_offer_rules(text: str | None) -> list[OfferRule]:
    if not text:
        return []
    rules: list[OfferRule] = []
    for match in re.finditer(r"\b(\d+)\s+for\s+(?:₹|rs\.?|inr)\s*([0-9]+(?:\.\d{1,2})?)", text, re.I):
        rules.append(OfferRule(bundle_qty=int(match.group(1)), bundle_price=Decimal(match.group(2)), source_text=match.group(0)))
    return rules


def price_for_quantity(quantity: int, base_price: Decimal | None, rules: list[OfferRule]) -> Decimal | None:
    if not base_price or quantity < 1:
        return None
    costs: list[Decimal | None] = [Decimal("0")] + [None] * quantity
    for current in range(1, quantity + 1):
        candidates = [costs[current - 1] + base_price] if costs[current - 1] is not None else []
        for rule in rules:
            if current >= rule.bundle_qty and costs[current - rule.bundle_qty] is not None:
                candidates.append(costs[current - rule.bundle_qty] + rule.bundle_price)
        costs[current] = min(candidates) if candidates else None
    return costs[quantity]


def listing_total(listing: RawListing, quantity: int) -> Decimal | None:
    return price_for_quantity(quantity, listing.price, parse_offer_rules(listing.offer_text))


def normalized_unit_price(product: NormalizedProduct) -> tuple[Decimal, str] | None:
    price, total = product.raw.price, product.total_amount_base
    if price is None or total is None or total <= 0:
        return None
    if product.measure_kind == "mass":
        return (price / Decimal(str(total)) * Decimal("100"), "/100 g")
    if product.measure_kind == "volume":
        return (price / Decimal(str(total)) * Decimal("100"), "/100 ml")
    if product.measure_kind == "count":
        return (price / Decimal(str(total)), "/piece")
    return None
