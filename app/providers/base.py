from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError

from app.config import MAX_RESULTS_PER_PROVIDER, PROVIDER_TIMEOUT_SECONDS
from app.models import RawListing

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Expected provider failure which can be shown as a provider status."""


class ProviderLocationError(ProviderError):
    pass


class GroceryProvider(ABC):
    name: str
    home_url: str

    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Page | None = None
        self.lock = asyncio.Lock()
        self.ready = False
        self.blocked = False
        self.last_error: str | None = None
        self.last_diagnostics: dict[str, str] = {}

    @abstractmethod
    async def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str) -> list[RawListing]:
        raise NotImplementedError

    @abstractmethod
    async def enrich(self, listing: RawListing) -> RawListing:
        raise NotImplementedError

    async def close(self) -> None:
        if self.page:
            await self.page.close()
            self.page = None

    async def _ensure_page(self) -> Page:
        if self.page is None or self.page.is_closed():
            self.page = await self.context.new_page()
            self.page.set_default_timeout(PROVIDER_TIMEOUT_SECONDS * 1000)
        return self.page

    async def _first_visible(self, selectors: Iterable[str], page: Page | None = None) -> Locator | None:
        target = page or await self._ensure_page()
        for selector in selectors:
            try:
                locator = target.locator(selector).first
                if await locator.count() and await locator.is_visible():
                    logger.debug("%s selector matched: %s", self.name, selector)
                    return locator
            except PlaywrightTimeoutError:
                continue
        return None

    @staticmethod
    def _money_values(text: str) -> list[Decimal]:
        cleaned = text.replace(",", "")
        values: list[Decimal] = []
        for match in re.finditer(r"(?:₹|Rs\.?|INR)\s*([0-9]+(?:\.[0-9]{1,2})?)", cleaned, re.I):
            try:
                values.append(Decimal(match.group(1)))
            except InvalidOperation:
                pass
        return values

    @classmethod
    def _prices_from_text(cls, text: str) -> tuple[Decimal | None, Decimal | None]:
        """Prefer explicitly labelled MRP over card-text order, then use a safe fallback."""
        regular_prices: list[Decimal] = []
        labelled_mrps: list[Decimal] = []
        for line in (line.strip() for line in text.splitlines() if line.strip()):
            values = cls._money_values(line)
            if not values:
                continue
            if re.search(r"\b(?:mrp|m\.r\.p\.)\b", line, re.I):
                labelled_mrps.extend(values)
            else:
                regular_prices.extend(values)
        if regular_prices:
            return regular_prices[0], labelled_mrps[0] if labelled_mrps else (regular_prices[1] if len(regular_prices) > 1 else None)
        values = cls._money_values(text)
        return (values[0] if values else None, labelled_mrps[0] if labelled_mrps else (values[1] if len(values) > 1 else None))

    @staticmethod
    def _size_from_text(text: str) -> str | None:
        patterns = (
            r"\b\d+\s*[x×]\s*\d+(?:\.\d+)?\s*(?:kg|g|gm|ml|l|pcs?)\b",
            r"\b\d+(?:\.\d+)?\s*(?:kg|g|gm|ml|l|pcs?)\s*[x×]\s*\d+\b",
            r"\bpack\s+of\s+\d+\b",
            r"\b\d+(?:\.\d+)?\s*(?:kg|kgs|g|gm|gms|grams?|ml|l|litre|liter|litres|liters|pcs?|pieces?)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def _availability(text: str) -> str:
        return "unavailable" if re.search(r"out\s+of\s+stock|unavailable|sold\s+out", text, re.I) else "unknown"

    @staticmethod
    def _canonical_url(url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))

    def _dedupe(self, listings: list[RawListing]) -> list[RawListing]:
        selected: dict[tuple[str, str], RawListing] = {}
        for listing in listings:
            if listing.provider_id:
                key = ("id", listing.provider_id)
            elif listing.product_url:
                key = ("url", self._canonical_url(listing.product_url) or "")
            else:
                key = ("fallback", f"{listing.title.casefold()}|{listing.size_text or ''}")
            previous = selected.get(key)
            if previous is None or (previous.sponsored and not listing.sponsored):
                selected[key] = listing
        return list(selected.values())[:MAX_RESULTS_PER_PROVIDER]

    async def _extract_anchor_cards(self, selectors: Iterable[str]) -> list[Locator]:
        page = await self._ensure_page()
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = min(await locator.count(), MAX_RESULTS_PER_PROVIDER * 3)
            except PlaywrightTimeoutError:
                continue
            visible: list[Locator] = []
            for index in range(count):
                item = locator.nth(index)
                try:
                    if await item.is_visible():
                        visible.append(item)
                except PlaywrightTimeoutError:
                    continue
            if visible:
                logger.debug("%s found %s cards with %s", self.name, len(visible), selector)
                return visible
        return []

    @staticmethod
    def _absolute_url(base: str, href: str | None) -> str | None:
        return urljoin(base, href) if href else None

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)


class UnavailableProvider:
    """Keeps the API alive when the browser driver itself cannot start."""

    def __init__(self, name: str, reason: str):
        self.name = name
        self.ready = False
        self.blocked = False
        self.last_error = reason

    async def initialize(self) -> None:
        return None

    async def search(self, query: str) -> list[RawListing]:
        raise ProviderError(self.last_error)

    async def enrich(self, listing: RawListing) -> RawListing:
        return listing

    async def close(self) -> None:
        return None
