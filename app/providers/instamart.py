from __future__ import annotations

import re
from pathlib import Path

from playwright.async_api import Locator, TimeoutError as PlaywrightTimeoutError

from app.config import DTU_LOCATION_QUERY, LOCATION_VERIFY_TOKENS
from app.models import RawListing
from app.providers.base import GroceryProvider, ProviderError, ProviderLocationError


class InstamartProvider(GroceryProvider):
    """Visible-DOM Instamart adapter. It does not call or emulate private endpoints."""

    name = "instamart"
    home_url = "https://www.swiggy.com/instamart"
    _BLOCK_PHRASES = (
        "your request looks automated and has been blocked",
        "request blocked",
    )

    async def initialize(self) -> None:
        async with self.lock:
            page = await self._ensure_page()
            try:
                await page.goto(self.home_url, wait_until="domcontentloaded", timeout=20_000)
                await page.wait_for_timeout(1500)
                body = await page.locator("body").inner_text()
                block_phrase = self._block_phrase(body)
                if block_phrase:
                    self.last_diagnostics = await self._capture_block_diagnostics(block_phrase, body)
                    raise ProviderError("Instamart blocked this browser session; no bypass was attempted.")
                if not await self._location_is_dtu():
                    await self._set_dtu_location()
                if not await self._location_is_dtu():
                    raise ProviderLocationError("Instamart did not show a verified DTU location after selection.")
                self.ready = True
                self.blocked = False
                self.last_error = None
                self.last_diagnostics = {}
            except Exception as exc:
                self.ready = False
                self.last_error = str(exc)
                self.blocked = "blocked" in self.last_error.casefold()
                raise

    @classmethod
    def _block_phrase(cls, body: str) -> str | None:
        """Match only the explicit rendered block messages, not generic site text."""
        for phrase in cls._BLOCK_PHRASES:
            match = re.search(re.escape(phrase), body, re.I)
            if match:
                return match.group(0)
        return None

    async def _capture_block_diagnostics(self, block_phrase: str, body: str) -> dict[str, str]:
        page = await self._ensure_page()
        debug_dir = Path("debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = debug_dir / "instamart_init_blocked.png"
        body_path = debug_dir / "instamart_init_body.txt"
        html_path = debug_dir / "instamart_init.html"
        title = await page.title()
        body_path.write_text(
            f"URL: {page.url}\nTitle: {title}\nBlock phrase: {block_phrase}\n\nVisible body:\n{body[:2000]}",
            encoding="utf-8",
        )
        diagnostics = {"body": str(body_path)}
        try:
            await page.screenshot(path=str(screenshot_path), full_page=True)
            diagnostics["screenshot"] = str(screenshot_path)
        except Exception as exc:
            diagnostics["screenshot_error"] = str(exc)
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
            diagnostics["html"] = str(html_path)
        except Exception as exc:
            diagnostics["html_error"] = str(exc)
        return diagnostics

    async def _location_is_dtu(self) -> bool:
        page = await self._ensure_page()
        body = (await page.locator("body").inner_text())[:14_000].casefold()
        return "delhi technological university" in body and any(token in body for token in LOCATION_VERIFY_TOKENS[1:])

    async def _set_dtu_location(self) -> None:
        page = await self._ensure_page()
        opener = await self._first_visible((
            "button:has-text('Select Location')",
            "text=Select Location",
            "button:has-text('Delivery')",
            "[aria-label*='location' i]",
        ))
        if opener:
            await opener.click()
        await page.wait_for_timeout(600)
        field = await self._first_visible((
            "input[placeholder*='area' i]",
            "input[placeholder*='location' i]",
            "input[placeholder*='Search' i]",
            "input[type='text']",
        ))
        if not field:
            raise ProviderLocationError("Instamart location search input was not visible.")
        await field.fill(DTU_LOCATION_QUERY)
        await page.wait_for_timeout(1500)
        suggestion = await self._first_visible((
            "text=Delhi Technological University, Shahbad Daulatpur Village, Rohini",
            "text=Delhi Technological University",
            "[role='option']:has-text('Delhi Technological University')",
        ))
        if not suggestion:
            raise ProviderLocationError("Instamart did not return a DTU location suggestion.")
        await suggestion.click()
        await page.wait_for_timeout(1800)

    async def _open_search(self) -> Locator:
        page = await self._ensure_page()
        field = await self._first_visible((
            "input[placeholder*='Search for' i]",
            "input[placeholder*='Search' i]",
            "input[type='search']",
        ))
        if field:
            return field
        trigger = await self._first_visible(("text=Search for items", "text=Search for products", "button:has-text('Search')"))
        if trigger:
            await trigger.click()
            await page.wait_for_timeout(350)
            field = await self._first_visible(("input[placeholder*='Search' i]", "input[type='search']"))
        if not field:
            raise ProviderError("Instamart search input was not visible.")
        return field

    async def search(self, query: str) -> list[RawListing]:
        if self.blocked:
            raise ProviderError(self.last_error or "Instamart blocked this browser session.")
        if not self.ready:
            await self.initialize()
        async with self.lock:
            page = await self._ensure_page()
            field = await self._open_search()
            await field.fill(query)
            await page.wait_for_timeout(2000)
            cards = await self._extract_anchor_cards((
                "a[href*='/instamart/item/']",
                "a[href*='/instamart/p/']",
                "a[href*='/item/']",
            ))
            results: list[RawListing] = []
            for card in cards:
                try:
                    listing = await self._parse_card(card)
                    if listing.title and listing.price and listing.price > 0:
                        results.append(listing)
                except Exception as exc:
                    self.last_error = f"Card parse skipped: {exc}"
            if not results:
                raise ProviderError("Instamart found no valid product cards; selectors may need calibration.")
            return self._dedupe(results)

    async def _parse_card(self, card: Locator) -> RawListing:
        raw_text = await card.inner_text()
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        price, mrp = self._prices_from_text(raw_text)
        href = await card.get_attribute("href")
        image = card.locator("img").first
        image_url = await image.get_attribute("src") if await image.count() else None
        return RawListing(
            platform="instamart",
            provider_id=self._provider_id(href),
            title=self._title_from_lines(lines, raw_text),
            size_text=self._size_from_text(raw_text),
            price=price,
            mrp=mrp,
            offer_text=self._offer_from_text(raw_text),
            image_url=image_url,
            product_url=self._absolute_url(self.home_url, href),
            sponsored=bool(re.search(r"\bsponsored\b|\bad\b", raw_text, re.I)),
            availability=self._availability(raw_text),
            raw_text=raw_text,
            fetched_at=self.now(),
        )

    @staticmethod
    def _provider_id(href: str | None) -> str | None:
        if not href:
            return None
        match = re.search(r"(?:item|product)[/_-](\d+)", href, re.I)
        return match.group(1) if match else None

    @staticmethod
    def _title_from_lines(lines: list[str], raw_text: str) -> str:
        ignored = re.compile(r"^(add|remove|out of stock|₹|rs\.?\s*\d|\d+(?:\.\d+)?\s*(?:g|kg|ml|l|pcs?)\b)", re.I)
        candidates = [line for line in lines if not ignored.search(line) and len(line) > 2]
        return max(candidates, key=len) if candidates else raw_text.split("₹")[0].strip()

    @staticmethod
    def _offer_from_text(text: str) -> str | None:
        match = re.search(r"\b(?:\d+\s+for\s+(?:₹|Rs\.?)[^\n]+|\d+%\s*off)\b", text, re.I)
        return match.group(0) if match else None

    async def enrich(self, listing: RawListing) -> RawListing:
        async with self.lock:
            return await self._enrich_unlocked(listing)

    async def _enrich_unlocked(self, listing: RawListing) -> RawListing:
        if not listing.product_url:
            return listing
        detail = await self.context.new_page()
        try:
            await detail.goto(listing.product_url, wait_until="domcontentloaded", timeout=15_000)
            cards = detail.locator("[data-testid='tabular-card-container']")
            for index in range(await cards.count()):
                text = await cards.nth(index).inner_text()
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                for pos, line in enumerate(lines[:-1]):
                    if line.casefold() in {"flavour", "flavor", "box contents", "pack size", "packaging type", "brand"}:
                        listing.attributes[line.casefold()] = lines[pos + 1]
            if listing.attributes.get("pack size"):
                listing.size_text = listing.attributes["pack size"]
            return listing
        except PlaywrightTimeoutError:
            return listing
        finally:
            await detail.close()
