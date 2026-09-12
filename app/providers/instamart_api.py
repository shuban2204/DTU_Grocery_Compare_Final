"""
QuickCommerce API Provider for Swiggy Instamart at Delhi Technological University.
Fetches structured live grocery listings via third-party QuickCommerce search API.
Implements quantity bundle consolidation and variant safety.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import (
    DTU_LAT,
    DTU_LON,
    MAX_RESULTS_PER_PROVIDER,
    PROVIDER_TIMEOUT_SECONDS,
    QUICKCOMMERCE_API_KEY,
    QUICKCOMMERCE_BASE_URL,
)
from app.models.listing import Availability, RawListing
from app.providers.base import ProviderError
from app.services.normalizer import _variant_tokens, normalize_text, parse_quantity

logger = logging.getLogger(__name__)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        clean = str(value).replace(",", "").strip()
        if not clean:
            return None
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return None


def _format_family_key(title: str, brand: str, parsed_q: Any) -> tuple:
    norm_title = normalize_text(title)
    # Temporary raw listing for variant extraction
    dummy = RawListing(platform="instamart", title=title, raw_text="", fetched_at=datetime.now(timezone.utc))
    variants = _variant_tokens(dummy, norm_title)
    # Strip quantity numbers, units, and stopwords for clean core identity
    clean_title = re.sub(r"\b\d+(?:\.\d+)?\s*(?:kg|g|gm|ml|l|pcs?)\b", "", norm_title)
    clean_title = re.sub(r"\b\d+\s*[x×]\s*\d+\b", "", clean_title)
    clean_title = re.sub(r"[x×]\s*\d+\b", "", clean_title)
    clean_title = " ".join(tok for tok in clean_title.split() if tok not in {"pack", "of", "combo", "x"})
    return (
        normalize_text(brand or ""),
        clean_title,
        tuple(sorted(variants)),
        parsed_q.base_unit,
        parsed_q.item_amount_base,
    )


class QuickCommerceInstamartProvider:
    """
    Integrates QuickCommerce API as the preferred live data provider for Swiggy Instamart at DTU.
    Conforms to the GroceryProvider duck-typed interface.
    """

    name = "instamart_api"
    home_url = "https://www.swiggy.com/instamart"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        timeout_seconds: int = PROVIDER_TIMEOUT_SECONDS,
    ):
        self.api_key = QUICKCOMMERCE_API_KEY if api_key is None else api_key
        self.base_url = QUICKCOMMERCE_BASE_URL if base_url is None else base_url
        self.lat = DTU_LAT if lat is None else lat
        self.lon = DTU_LON if lon is None else lon
        self.timeout_seconds = timeout_seconds
        self.ready = False
        self.blocked = False
        self.last_error: str | None = None
        self.last_diagnostics: dict[str, str] = {}
        self.last_credits_remaining: int | None = None

    async def initialize(self) -> None:
        if not self.api_key or not self.api_key.strip():
            self.ready = False
            self.last_error = "QUICKCOMMERCE_API_KEY is not configured"
            logger.info("QuickCommerceInstamartProvider disabled: QUICKCOMMERCE_API_KEY not set")
            return

        self.ready = True
        self.blocked = False
        self.last_error = None
        logger.info(
            "QuickCommerceInstamartProvider initialized for DTU (lat=%s, lon=%s)",
            self.lat,
            self.lon,
        )

    def _sync_request(self, query: str) -> str:
        params = {
            "q": query,
            "platform": "Swiggy",
            "lat": str(self.lat),
            "lon": str(self.lon),
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        headers = {
            "X-API-Key": self.api_key or "",
            "Accept": "application/json",
            "User-Agent": "DTU-Grocery-Compare/1.0",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=ctx) as resp:
                status = resp.status
                body = resp.read().decode("utf-8", errors="replace")
                if status != 200:
                    raise ProviderError(f"QuickCommerce API responded with HTTP {status}")
                return body
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"QuickCommerce API HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"QuickCommerce API connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderError("QuickCommerce API request timed out") from exc

    async def search(self, query: str) -> list[RawListing]:
        if not self.api_key or not self.api_key.strip():
            raise ProviderError("QUICKCOMMERCE_API_KEY is not configured")

        try:
            body = await asyncio.to_thread(self._sync_request, query)
        except Exception as exc:
            self.last_error = str(exc)
            raise

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            self.last_error = f"Malformed JSON: {exc}"
            raise ProviderError(f"QuickCommerce API returned invalid JSON: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("status") != "success":
            msg = payload.get("message", "API response unsuccessful") if isinstance(payload, dict) else "Invalid response"
            self.last_error = msg
            raise ProviderError(f"QuickCommerce API error: {msg}")

        # Protect account info: log credits remaining at debug level only
        credits_remaining = payload.get("credits_remaining")
        if credits_remaining is not None:
            self.last_credits_remaining = credits_remaining
            logger.debug("QuickCommerce API credits remaining: %s", credits_remaining)

        raw_products = payload.get("data", {}).get("products", [])
        if not isinstance(raw_products, list):
            return []

        observed_at = datetime.now(timezone.utc)
        return self._parse_and_consolidate(raw_products, observed_at)

    def _parse_and_consolidate(self, items: list[dict[str, Any]], observed_at: datetime) -> list[RawListing]:
        """
        Parses raw API items and collapses quantity bundles (e.g. 750 ml x 2, 750 ml x 12)
        into their respective base listings with pricing engine offer rules.
        """
        # Step 1: Parse intermediate catalog items
        parsed_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            brand = str(item.get("brand") or "").strip()
            # Ensure brand is in title so query relevance and matcher can accurately identify product
            if brand and normalize_text(brand) not in normalize_text(name):
                full_title = f"{brand} {name}"
            else:
                full_title = name


            raw_qty = str(item.get("quantity") or "").strip()
            parsed_q = parse_quantity(raw_qty)

            price = _to_decimal(item.get("offer_price"))
            mrp = _to_decimal(item.get("mrp"))

            avail_bool = item.get("available")
            availability: Availability = (
                "available" if avail_bool is True else "unavailable" if avail_bool is False else "unknown"
            )

            images = item.get("images")
            image_url = images[0] if isinstance(images, list) and images else None
            product_url = item.get("deeplink") or None
            sponsored = bool(item.get("is_ad", False))

            attributes: dict[str, str] = {}
            if item.get("id"):
                attributes["api_id"] = str(item["id"])
            if item.get("store_id"):
                attributes["store_id"] = str(item["store_id"])
            if brand:
                attributes["brand"] = brand

            raw_text = f"{full_title} | {raw_qty} | ₹{price or '—'}"

            parsed_items.append({
                "title": full_title,
                "brand": brand,
                "size_text": raw_qty,
                "parsed_q": parsed_q,
                "price": price,
                "mrp": mrp,
                "availability": availability,
                "image_url": image_url,
                "product_url": product_url,
                "sponsored": sponsored,
                "attributes": attributes,
                "raw_text": raw_text,
                "family_key": _format_family_key(full_title, brand, parsed_q),
            })

        # Step 2: Group by product identity family to collapse bundles
        groups: dict[tuple, list[dict[str, Any]]] = {}
        for p in parsed_items:
            key = p["family_key"]
            groups.setdefault(key, []).append(p)

        consolidated: list[RawListing] = []
        for key, group in groups.items():
            # Check if there is a single unit item in this family
            single_units = [x for x in group if x["parsed_q"].pack_count == 1]
            bundles = [x for x in group if x["parsed_q"].pack_count > 1]

            if single_units:
                # Use the primary single-unit row as the base listing
                base = single_units[0]
                offers: list[str] = []
                for b in sorted(bundles, key=lambda x: x["parsed_q"].pack_count):
                    count = b["parsed_q"].pack_count
                    b_price = b["price"]
                    if b_price is not None:
                        offers.append(f"{count} for ₹{b_price}")

                offer_text = "; ".join(offers) if offers else None

                consolidated.append(
                    RawListing(
                        platform="instamart",
                        provider_id=base["attributes"].get("api_id"),
                        title=base["title"],
                        size_text=base["size_text"],
                        price=base["price"],
                        mrp=base["mrp"],
                        offer_text=offer_text,
                        image_url=base["image_url"],
                        product_url=base["product_url"],
                        sponsored=base["sponsored"],
                        availability=base["availability"],
                        raw_text=base["raw_text"],
                        fetched_at=observed_at,
                        attributes=base["attributes"],
                    )
                )
            else:
                # No single-unit item exists; keep bundles as distinct pack listings
                for b in group:
                    consolidated.append(
                        RawListing(
                            platform="instamart",
                            provider_id=b["attributes"].get("api_id"),
                            title=b["title"],
                            size_text=b["size_text"],
                            price=b["price"],
                            mrp=b["mrp"],
                            offer_text=None,
                            image_url=b["image_url"],
                            product_url=b["product_url"],
                            sponsored=b["sponsored"],
                            availability=b["availability"],
                            raw_text=b["raw_text"],
                            fetched_at=observed_at,
                            attributes=b["attributes"],
                        )
                    )

        return consolidated[:MAX_RESULTS_PER_PROVIDER]

    async def enrich(self, listing: RawListing) -> RawListing:
        # API listings already have full structured data; no-op to avoid browser automation
        return listing

    async def close(self) -> None:
        return None
