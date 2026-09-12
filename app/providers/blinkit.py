from __future__ import annotations

import logging
import re
from decimal import Decimal
from pathlib import Path

from playwright.async_api import Locator, TimeoutError as PlaywrightTimeoutError

from app.config import DTU_LOCATION_QUERY, MAX_RESULTS_PER_PROVIDER
from app.models import RawListing
from app.providers.base import GroceryProvider, ProviderError, ProviderLocationError

logger = logging.getLogger(__name__)


class BlinkitProvider(GroceryProvider):
    """Visible-DOM Blinkit adapter. Selectors deliberately stay in this module."""

    name = "blinkit"
    home_url = "https://blinkit.com/"

    # These remain local to Blinkit because they describe its rendered location UI.
    _LOCATION_MODAL_SELECTORS = (
        "[class*='LocationDropDown__LocationModalContainer']",
        "[role='dialog']:has(input[placeholder*='location' i])",
    )
    _LOCATION_INPUT_SELECTORS = (
        "input[placeholder*='search delivery location' i]",
        "input[placeholder*='delivery location' i]",
        "input[placeholder*='Search' i]",
        "input[placeholder*='location' i]",
        "input[aria-label*='location' i]",
        "input[type='text']",
    )
    _LOCATION_HEADER_SELECTORS = (
        "header",
        "[class*='LocationDropDown__LocationAddress']",
        "[class*='LocationDropDown__LocationName']",
        "[class*='LocationDropDown__LocationText']",
        "button[aria-label*='location' i]",
    )
    _EDITABLE_SEARCH_SELECTORS = (
        "input[placeholder^='Search' i]",
        "input[placeholder*='Search' i]",
        "input[type='search']",
        "[role='textbox'][contenteditable='true']",
    )
    _SEARCH_LAUNCHER_SELECTORS = (
        "[role='button'][aria-label*='search' i]",
        "button[aria-label*='search' i]",
        "button:has-text('Search')",
        "[role='button']:has-text('Search')",
    )
    _PRODUCT_CARD_SELECTORS = (
        "div[role='button'][id]:has-text('₹')",
        "div[role='button']:has(div[class*='tw-line-clamp-2']):has-text('₹')",
        "div[role='button']:has-text('ADD'):has-text('₹')",
        "div[id]:has(div[class*='tw-line-clamp-2']):has-text('₹')",
        "a[href*='/prn/']",
        "a[href*='/p/']",
        "a[href*='product']",
    )

    async def initialize(self) -> None:
        async with self.lock:
            page = await self._ensure_page()
            try:
                self._location_trigger_clicked = False
                self._location_input_selector_used = None
                self._last_location_suggestion_texts: list[str] = []
                logger.debug("Blinkit location trigger clicked: false")
                await page.goto(self.home_url, wait_until="domcontentloaded", timeout=20_000)
                await page.wait_for_timeout(1200)
                # Blinkit normally opens this modal automatically. Check it before any header trigger.
                initial_location_input = await self._visible_location_input()
                logger.debug("Blinkit location input visible initially: %s", initial_location_input is not None)
                body = (await page.locator("body").inner_text()).casefold()
                if "access denied" in body or "you have been blocked" in body:
                    raise ProviderError("Blinkit blocked this browser session; no bypass was attempted.")
                if not await self._location_is_dtu():
                    try:
                        await self._set_dtu_location(initial_location_input)
                    except Exception:
                        await self._capture_location_diagnostics("Unable to fill or select the DTU location.")
                        raise
                final_location_text = await self._header_location_text()
                verification_passed = "delhi technological university" in final_location_text.casefold()
                logger.debug("Blinkit final location text: %s (verified: %s)", final_location_text, verification_passed)
                if not verification_passed:
                    await self._capture_location_diagnostics("Blinkit header/location area did not show Delhi Technological University after selection.")
                    raise ProviderLocationError("Blinkit did not show Delhi Technological University in the active header location after selection.")
                try:
                    await self._capture_search_state("before", "Before Maggi verification search.")
                    maggi_results = await self._search_unlocked("Maggi")
                    logger.debug("Blinkit Maggi verification listings: %s", len(maggi_results))
                except Exception as exc:
                    await self._capture_search_state("after", f"Maggi verification search failed: {exc}")
                    raise ProviderError(f"Blinkit Maggi verification search failed: {exc}") from exc
                self.ready = True
                self.blocked = False
                self.last_error = None
                logger.info("Blinkit initialized for Delhi Technological University")
            except Exception as exc:
                self.ready = False
                self.last_error = str(exc)
                self.blocked = "blocked" in self.last_error.casefold()
                raise

    async def _location_is_dtu(self) -> bool:
        return "delhi technological university" in (await self._header_location_text()).casefold()

    async def _header_location_text(self) -> str:
        page = await self._ensure_page()
        # Verify only from the visible location/header controls, never arbitrary page content.
        texts: list[str] = []
        for selector in self._LOCATION_HEADER_SELECTORS:
            locator = page.locator(selector)
            for index in range(await locator.count()):
                candidate = locator.nth(index)
                if await candidate.is_visible():
                    text = (await candidate.inner_text()).strip()
                    if text:
                        texts.append(text)
        return " | ".join(texts)

    async def _visible_location_input(self) -> Locator | None:
        """Return the already-open modal's input, if a Blinkit location modal is visible."""
        page = await self._ensure_page()
        # Semantic placeholder selectors are attempted before the class-name-stem fallback.
        for input_selector in self._LOCATION_INPUT_SELECTORS[:2]:
            field = page.locator(input_selector).first
            if await field.count() and await field.is_visible():
                self._location_input_selector_used = input_selector
                logger.debug("Blinkit location input selector used: %s", input_selector)
                return field
        for modal_selector in self._LOCATION_MODAL_SELECTORS:
            modals = page.locator(modal_selector)
            for modal_index in range(await modals.count()):
                modal = modals.nth(modal_index)
                if not await modal.is_visible():
                    continue
                for input_selector in self._LOCATION_INPUT_SELECTORS:
                    field = modal.locator(input_selector).first
                    if await field.count() and await field.is_visible():
                        self._location_input_selector_used = f"{modal_selector} >> {input_selector}"
                        logger.debug("Blinkit location input selector used: %s", self._location_input_selector_used)
                        return field
        return None

    async def _click_location_opener(self) -> None:
        opener = await self._first_visible((
            "button:has-text('Select Location')",
            "button:has-text('Delivery')",
            "text=Select Location",
            "[aria-label*='location' i]",
        ))
        if not opener:
            raise ProviderLocationError("Blinkit location opener was not visible.")
        await opener.click()
        self._location_trigger_clicked = True
        logger.debug("Blinkit location opener clicked: true")

    async def _wait_for_location_input(self) -> Locator | None:
        # The modal is normally already open. If it was just opened, wait briefly for it to render.
        page = await self._ensure_page()
        for _ in range(12):
            field = await self._visible_location_input()
            if field:
                return field
            await page.wait_for_timeout(250)
        return None

    async def _dtu_suggestion(self) -> Locator | None:
        page = await self._ensure_page()
        candidates = page.get_by_text(re.compile(r"Delhi Technological University", re.I))
        texts = await self._visible_location_suggestion_texts()
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if not await candidate.is_visible():
                continue
            raw_text = (await candidate.inner_text()).strip()
            if raw_text not in texts:
                texts.append(raw_text)
            text = raw_text.casefold()
            if "delhi technological university" in text and ("rohini" in text or "shahbad daulatpur" in text):
                self._last_location_suggestion_texts = texts
                logger.debug("Blinkit suggestion count: %s, selected: %s", len(texts), raw_text)
                return candidate
        self._last_location_suggestion_texts = texts
        logger.debug("Blinkit suggestion count: %s", len(texts))
        return None

    async def _visible_location_suggestion_texts(self) -> list[str]:
        """Collect visible modal suggestion text for precise failure diagnostics."""
        page = await self._ensure_page()
        texts: list[str] = []
        for modal_selector in self._LOCATION_MODAL_SELECTORS:
            modals = page.locator(modal_selector)
            for modal_index in range(await modals.count()):
                modal = modals.nth(modal_index)
                if not await modal.is_visible():
                    continue
                options = modal.locator("[role='option'], li, button")
                for option_index in range(await options.count()):
                    option = options.nth(option_index)
                    if await option.is_visible():
                        text = (await option.inner_text()).strip()
                        if text and text not in texts:
                            texts.append(text)
        return texts

    async def _wait_for_dtu_suggestion(self) -> Locator | None:
        page = await self._ensure_page()
        for _ in range(12):
            suggestion = await self._dtu_suggestion()
            if suggestion is not None:
                return suggestion
            await page.wait_for_timeout(250)
        return None

    async def _set_dtu_location(self, initial_location_input: Locator | None = None) -> None:
        page = await self._ensure_page()
        field = initial_location_input if initial_location_input is not None else await self._visible_location_input()
        if not field:
            await self._click_location_opener()
            field = await self._wait_for_location_input()
        if not field:
            raise ProviderLocationError("Blinkit location search input was not visible.")
        await field.fill(DTU_LOCATION_QUERY)
        suggestion = await self._wait_for_dtu_suggestion()
        if not suggestion:
            suggestion_texts = getattr(self, "_last_location_suggestion_texts", [])
            raise ProviderLocationError(f"Blinkit did not return the DTU Rohini/Shahbad Daulatpur location suggestion. Visible DTU suggestions: {suggestion_texts}")
        await suggestion.click()
        await page.wait_for_timeout(1800)

    async def _capture_location_diagnostics(self, reason: str) -> None:
        page = await self._ensure_page()
        debug_dir = Path("debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        body = await page.locator("body").inner_text()
        (debug_dir / "blinkit_location_modal_body.txt").write_text(
            f"URL: {page.url}\nReason: {reason}\nLocation input selector: {getattr(self, '_location_input_selector_used', None)}\n"
            f"Trigger clicked: {getattr(self, '_location_trigger_clicked', False)}\nSuggestions: {getattr(self, '_last_location_suggestion_texts', [])}\n\n"
            f"Visible body:\n{body[:4000]}",
            encoding="utf-8",
        )
        try:
            await page.screenshot(path=str(debug_dir / "blinkit_location_modal.png"), full_page=True)
        except Exception as exc:
            logger.warning("Blinkit location screenshot capture failed: %s", exc)
        try:
            (debug_dir / "blinkit_location_modal.html").write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("Blinkit location HTML capture failed: %s", exc)

    async def _capture_search_state(self, state: str, reason: str) -> None:
        page = await self._ensure_page()
        debug_dir = Path("debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        body = await page.locator("body").inner_text()
        (debug_dir / f"blinkit_search_{state}_body.txt").write_text(
            f"URL: {page.url}\nReason: {reason}\nSearch input selector: {getattr(self, '_search_input_selector_used', None)}\n"
            f"Search launcher selector: {getattr(self, '_search_launcher_selector', None)}\n"
            f"Candidate search elements: {getattr(self, '_search_candidate_elements', [])}\n\nVisible body:\n{body[:4000]}",
            encoding="utf-8",
        )
        try:
            await page.screenshot(path=str(debug_dir / f"blinkit_search_{state}.png"), full_page=True)
        except Exception as exc:
            logger.warning("Blinkit search screenshot capture failed: %s", exc)
        try:
            (debug_dir / f"blinkit_search_{state}.html").write_text(await page.content(), encoding="utf-8")
            if getattr(self, "_search_launcher_html", ""):
                (debug_dir / "blinkit_search_parent.html").write_text(self._search_launcher_html, encoding="utf-8")
            cards = page.locator("div[role='button'][id]:has-text('₹'), a[href*='/prn/'], a[href*='/p/'], a[href*='product']")
            card_html = await cards.evaluate_all("els => els.slice(0, 12).map(el => el.outerHTML).join('\\n<!-- CARD -->\\n')")
            (debug_dir / f"blinkit_search_{state}_cards.html").write_text(card_html, encoding="utf-8")
        except Exception as exc:
            logger.warning("Blinkit search HTML/card capture was incomplete: %s", exc)

    async def _open_search(self) -> Locator:
        page = await self._ensure_page()
        self._search_candidate_elements: list[str] = []
        logger.debug("Blinkit URL before search: %s", page.url)
        field = await self._visible_editable_search_input()
        logger.debug("Blinkit editable search input visible initially: %s", field is not None)
        if field is not None:
            return field
        launcher = await self._homepage_search_launcher()
        logger.debug("Blinkit homepage search launcher found: %s", launcher is not None)
        if launcher is None:
            await self._capture_search_state("before", "No editable Blinkit search input or homepage search launcher was visible.")
            await self._capture_search_state("after", "Search UI could not be opened because no launcher was found.")
            raise ProviderError("Blinkit search input and homepage search launcher were not visible.")
        await self._capture_search_state("before", "Homepage search launcher found; opening editable search UI.")
        try:
            await launcher.click()
            logger.debug("Blinkit homepage search launcher clicked")
        except Exception as exc:
            await self._capture_search_state("after", f"Homepage search launcher click failed: {exc}")
            raise ProviderError(f"Blinkit homepage search launcher could not be clicked: {exc}") from exc
        field = await self._wait_for_editable_search_input()
        logger.debug("Blinkit editable search input visible after click: %s", field is not None)
        if field is None:
            await self._capture_search_state("after", "Editable Blinkit search input did not appear after opening the homepage launcher.")
            raise ProviderError("Blinkit search input was not visible.")
        return field

    async def _visible_editable_search_input(self) -> Locator | None:
        """Find a visible editable product-search field, never the delivery-location input."""
        page = await self._ensure_page()
        for selector in self._EDITABLE_SEARCH_SELECTORS:
            fields = page.locator(selector)
            for index in range(await fields.count()):
                field = fields.nth(index)
                if not await field.is_visible():
                    continue
                placeholder = (await field.get_attribute("placeholder") or "").casefold()
                aria_label = (await field.get_attribute("aria-label") or "").casefold()
                if "delivery location" in placeholder or "delivery location" in aria_label:
                    continue
                if await field.get_attribute("disabled") is not None or await field.get_attribute("readonly") is not None:
                    continue
                self._search_input_selector_used = selector
                logger.debug("Blinkit search input selector used: %s", selector)
                return field
        # Role-based fallback is useful when Blinkit renders a semantic contenteditable textbox.
        fields = page.get_by_role("textbox")
        for index in range(await fields.count()):
            field = fields.nth(index)
            if not await field.is_visible():
                continue
            placeholder = (await field.get_attribute("placeholder") or "").casefold()
            aria_label = (await field.get_attribute("aria-label") or "").casefold()
            if "delivery location" in placeholder or "delivery location" in aria_label:
                continue
            self._search_input_selector_used = "get_by_role('textbox')"
            logger.debug("Blinkit search input selector used: %s", self._search_input_selector_used)
            return field
        return None

    async def _homepage_search_launcher(self) -> Locator | None:
        page = await self._ensure_page()
        self._animated_search_child_found = False
        self._stable_search_parent_found = False
        self._search_launcher_selector = None
        self._search_launcher_html = ""
        stable_parent = await self._stable_search_bar_parent()
        if stable_parent is not None:
            return stable_parent
        for selector in self._SEARCH_LAUNCHER_SELECTORS:
            candidates = page.locator(selector)
            for index in range(await candidates.count()):
                candidate = candidates.nth(index)
                if not await candidate.is_visible():
                    continue
                await self._record_search_launcher(candidate, selector)
                return candidate
        return None

    async def _stable_search_bar_parent(self) -> Locator | None:
        """Use the stable SearchBar ancestor, never the moving animationText child."""
        page = await self._ensure_page()
        animated_children = page.locator("div[id^='animationText-']")
        for index in range(await animated_children.count()):
            animated_child = animated_children.nth(index)
            if not await animated_child.is_visible():
                continue
            self._animated_search_child_found = True
            parent = animated_child.locator("xpath=ancestor::*[contains(@class, 'SearchBar__')][1]")
            if not await parent.count() or not await parent.is_visible():
                continue
            self._stable_search_parent_found = True
            await self._record_search_launcher(parent, "div[id^='animationText-'] -> ancestor::*[contains(@class, 'SearchBar__')][1]")
            logger.debug("Blinkit stable SearchBar ancestor found")
            return parent
        logger.debug("Blinkit stable SearchBar ancestor not found (animated child: %s)", self._animated_search_child_found)
        return None

    async def _record_search_launcher(self, candidate: Locator, selector: str) -> None:
        self._search_launcher_selector = selector
        self._search_candidate_elements.append(await self._describe_search_candidate(candidate))
        self._search_launcher_html = await candidate.evaluate("el => el.outerHTML")
        logger.debug("Blinkit search launcher recorded: %s", selector)

    async def _describe_search_candidate(self, candidate: Locator) -> str:
        tag = await candidate.evaluate("el => el.tagName.toLowerCase()")
        role = await candidate.get_attribute("role") or ""
        text = (await candidate.inner_text()).strip()
        return f"tag={tag}; role={role or '-'}; text={text[:300]}"

    async def _wait_for_editable_search_input(self) -> Locator | None:
        page = await self._ensure_page()
        for _ in range(12):
            field = await self._visible_editable_search_input()
            if field is not None:
                return field
            await page.wait_for_timeout(250)
        return None

    async def search(self, query: str) -> list[RawListing]:
        if self.blocked:
            raise ProviderError(self.last_error or "Blinkit blocked this browser session.")
        if not self.ready:
            await self.initialize()
        async with self.lock:
            return await self._search_unlocked(query)

    async def _search_unlocked(self, query: str) -> list[RawListing]:
        page = await self._ensure_page()
        field = await self._open_search()
        await field.fill(query)
        cards = await self._wait_for_search_results()
        logger.debug("Blinkit query '%s' result card count: %s", query, len(cards))
        results: list[RawListing] = []
        for card in cards:
            try:
                listing = await self._parse_card(card)
                if listing.title and listing.price and listing.price > 0:
                    results.append(listing)
            except Exception as exc:
                # A single malformed product card must not drop a whole provider response.
                self.last_error = f"Card parse skipped: {exc}"
        if not results:
            raise ProviderError("Blinkit found no valid product cards; selectors may need calibration.")
        extracted = self._dedupe(results)
        logger.info("Blinkit search '%s' -> %d listings extracted", query, len(extracted))
        return extracted

    async def _wait_for_search_results(self) -> list[Locator]:
        page = await self._ensure_page()
        for _ in range(24):
            cards = await self._product_result_cards()
            if cards:
                return cards
            if await self._is_empty_search_results():
                logger.debug("Blinkit empty search results appeared with no product cards.")
                return []
            await page.wait_for_timeout(250)
        return []

    async def _is_empty_search_results(self) -> bool:
        page = await self._ensure_page()
        for phrase in ("no results found", "could not find any results", "we couldn't find any products", "no products found"):
            locator = page.get_by_text(re.compile(re.escape(phrase), re.I))
            for i in range(await locator.count()):
                if await locator.nth(i).is_visible():
                    return True
        return False

    async def _product_result_cards(self) -> list[Locator]:
        page = await self._ensure_page()
        for selector in self._PRODUCT_CARD_SELECTORS:
            locator = page.locator(selector)
            try:
                count = min(await locator.count(), MAX_RESULTS_PER_PROVIDER * 3)
            except PlaywrightTimeoutError:
                continue
            if count:
                cards: list[Locator] = []
                seen_ids: set[str] = set()
                for i in range(count):
                    card = locator.nth(i)
                    try:
                        if not await card.is_visible():
                            continue
                        cid = await card.get_attribute("id") or ""
                        if cid == "product_container":
                            continue
                        if cid and cid in seen_ids:
                            continue
                        if cid:
                            seen_ids.add(cid)
                        tag = await card.evaluate("el => el.tagName.toLowerCase()")
                        if tag == "a":
                            ancestor = card.locator("xpath=ancestor::*[@role='listitem' or self::article][1]")
                            if not await ancestor.count():
                                ancestor = card.locator("xpath=ancestor::div[.//img and (.//button or @role='button')][1]")
                            if await ancestor.count() and await ancestor.is_visible():
                                cards.append(ancestor)
                                continue
                        cards.append(card)
                    except PlaywrightTimeoutError:
                        continue
                if cards:
                    logger.debug("Blinkit found %s cards with %s", len(cards), selector)
                    return cards
        return []

    async def _parse_card(self, card: Locator) -> RawListing:
        raw_text = await card.inner_text()
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        price, mrp = self._prices_from_text(raw_text)

        if mrp is None:
            strikethrough = card.locator("div[class*='tw-line-through'], [style*='line-through']").first
            if await strikethrough.count():
                try:
                    st_prices = self._money_values(await strikethrough.inner_text())
                    if st_prices:
                        mrp = st_prices[0]
                except Exception:
                    pass

        # Title: prefer semantic line-clamp-2 element, fallback to lines
        title = ""
        title_el = card.locator("div[class*='tw-line-clamp-2'], [data-test-id*='title'], h2, h3").first
        if await title_el.count() and await title_el.is_visible():
            title = (await title_el.inner_text()).strip()
        if not title:
            title = self._title_from_lines(lines, raw_text)

        # Size: prefer semantic line-clamp-1 size element, fallback to text regex
        size_text = None
        size_el = card.locator("div[class*='tw-line-clamp-1']").first
        if await size_el.count() and await size_el.is_visible():
            size_text = self._size_from_text(await size_el.inner_text())
        if not size_text:
            size_text = self._size_from_text(raw_text)

        href = await card.get_attribute("href")
        if not href:
            product_link = card.locator("a[href*='/prn/'], a[href*='/p/'], a[href*='product']").first
            if await product_link.count():
                href = await product_link.get_attribute("href")

        card_id = await card.get_attribute("id")
        provider_id = (self._provider_id(href) if href else None) or (card_id if (card_id and card_id != "product_container") else None)

        if href:
            product_url = self._absolute_url(self.home_url, href)
        elif provider_id:
            slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
            product_url = f"https://blinkit.com/prn/{slug or 'product'}/prid/{provider_id}"
        else:
            product_url = None

        image = card.locator("img[src*='product'], img[src*='cms'], img").first
        image_url = await image.get_attribute("src") if await image.count() else None

        is_sponsored = bool(
            await card.locator("img[src*='ad_without_bg'], [aria-label*='sponsored' i], [aria-label='Ad' i]").count()
            or re.search(r"\b(?:sponsored|ad)\b", raw_text, re.I)
        )

        if re.search(r"out\s+of\s+stock|unavailable|sold\s+out", raw_text, re.I):
            availability = "unavailable"
        elif re.search(r"\badd\b", raw_text, re.I):
            availability = "available"
        else:
            availability = self._availability(raw_text)

        return RawListing(
            platform="blinkit",
            provider_id=provider_id,
            title=title,
            size_text=size_text,
            price=price,
            mrp=mrp,
            offer_text=self._offer_from_text(raw_text),
            image_url=image_url,
            product_url=product_url,
            sponsored=is_sponsored,
            availability=availability,
            raw_text=raw_text,
            fetched_at=self.now(),
        )

    @staticmethod
    def _provider_id(href: str | None) -> str | None:
        if not href:
            return None
        match = re.search(r"(?:prid|product_id|id)[=/]([^/?#]+)", href, re.I)
        return match.group(1) if match else None

    @staticmethod
    def _title_from_lines(lines: list[str], raw_text: str) -> str:
        ignored = re.compile(r"^(add|remove|out of stock|₹|rs\.?\s*\d|\d+(?:\.\d+)?\s*(?:g|kg|ml|l|pcs?)\b)", re.I)
        candidates = [line for line in lines if not ignored.search(line) and len(line) > 2]
        return max(candidates, key=len) if candidates else raw_text.split("₹")[0].strip()

    @staticmethod
    def _offer_from_text(text: str) -> str | None:
        match = re.search(r"\b(?:\d+\s+for\s+(?:₹|Rs\.?)[^\n]+|\d+%\s*off)\b", text, re.I)
        if not match:
            return None
        return re.sub(r"\s+", " ", match.group(0)).strip()

    async def enrich(self, listing: RawListing) -> RawListing:
        async with self.lock:
            return await self._enrich_unlocked(listing)

    async def _enrich_unlocked(self, listing: RawListing) -> RawListing:
        if not listing.product_url:
            return listing
        detail = await self.context.new_page()
        try:
            await detail.goto(listing.product_url, wait_until="domcontentloaded", timeout=15_000)
            labels = (
                "Pack Size", "Unit", "Net Quantity", "Volume", "Weight",
                "Flavour", "Flavor", "Brand", "Product Type", "Type",
            )
            for label in labels:
                matches = detail.get_by_text(label, exact=True)
                if not await matches.count():
                    matches = detail.get_by_text(re.compile(rf"^{re.escape(label)}[:\s]*$", re.I))
                if await matches.count():
                    row = matches.first.locator("xpath=..")
                    if await row.count():
                        text = await row.inner_text()
                        value = re.sub(rf"^{re.escape(label)}", "", text, flags=re.I).strip(" :\n\t")
                        if value:
                            listing.attributes[label.casefold()] = value
            for size_key in ("pack size", "unit", "net quantity", "volume", "weight"):
                val = listing.attributes.get(size_key)
                if val:
                    parsed = self._size_from_text(val)
                    if parsed:
                        listing.size_text = parsed
                        break
                    if len(val) < 25:
                        listing.size_text = val
                        break
            return listing
        except Exception:
            return listing
        finally:
            await detail.close()
