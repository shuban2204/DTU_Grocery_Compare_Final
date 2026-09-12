"""Transparent manually captured Instamart data; never a substitute for live retrieval."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import RawListing


class InstamartSnapshotProvider:
    """Implements the provider methods using developer-maintained JSON snapshots."""

    name = "instamart_snapshot"
    home_url = "https://www.swiggy.com/instamart"

    def __init__(self, snapshot_dir: Path | None = None):
        self.snapshot_dir = snapshot_dir or Path("data") / "instamart_snapshots"
        self.ready = False
        self.blocked = False
        self.last_error: str | None = None
        self.last_diagnostics: dict[str, str] = {}
        self.last_snapshot_info: dict[str, Any] = {}

    async def initialize(self) -> None:
        self.ready = True
        self.blocked = False
        self.last_error = None

    @staticmethod
    def _key(query: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", query.casefold()).strip("_")

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    async def search(self, query: str) -> list[RawListing]:
        path = self.snapshot_dir / f"{self._key(query)}.json"
        if not path.exists():
            self.last_snapshot_info = {"available": False, "query": query, "message": "Instamart data unavailable for this query."}
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.last_snapshot_info = {"available": False, "query": query, "message": f"Instamart snapshot could not be read: {exc}"}
            return []
        captured_at = self._parse_timestamp(payload.get("captured_at"))
        products = payload.get("products") if isinstance(payload.get("products"), list) else []
        self.last_snapshot_info = {
            "available": bool(products),
            "query": payload.get("query", query),
            "location": payload.get("location"),
            "captured_at": captured_at,
            "source": payload.get("source", "manual_snapshot"),
            "path": str(path),
            "message": None if products else "Instamart data unavailable for this query.",
        }
        observed_at = captured_at or datetime.now(timezone.utc)
        listings: list[RawListing] = []
        for product in products:
            if not isinstance(product, dict) or not str(product.get("title", "")).strip():
                continue
            availability = product.get("availability", "unknown")
            if availability not in {"available", "unavailable", "unknown"}:
                availability = "unknown"
            raw_text = product.get("raw_text") or " | ".join(str(value) for value in (product.get("title"), product.get("size"), product.get("price")) if value)
            listings.append(RawListing(
                platform="instamart",
                provider_id=product.get("provider_id"),
                title=str(product["title"]),
                size_text=product.get("size"),
                price=product.get("price"),
                mrp=product.get("mrp"),
                offer_text=product.get("offer_text"),
                image_url=product.get("image_url"),
                product_url=product.get("product_url"),
                sponsored=bool(product.get("sponsored", False)),
                availability=availability,
                raw_text=raw_text,
                fetched_at=observed_at,
                attributes=product.get("attributes") if isinstance(product.get("attributes"), dict) else {},
            ))
        self.last_snapshot_info["available"] = bool(listings)
        return listings

    async def enrich(self, listing: RawListing) -> RawListing:
        return listing

    async def close(self) -> None:
        return None
