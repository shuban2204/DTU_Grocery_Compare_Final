import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from unittest.mock import AsyncMock

from app.models import RawListing
from app.providers.base import GroceryProvider
from app.providers.blinkit import BlinkitProvider
from app.providers.instamart import InstamartProvider


def test_multipack_text_is_not_reduced_to_one_item_size():
    assert GroceryProvider._size_from_text("Maggi Masala 4 x 70 g") == "4 x 70 g"
    assert GroceryProvider._size_from_text("Maggi Masala 70 g x 4") == "70 g x 4"


def test_explicit_mrp_does_not_replace_the_current_price():
    price, mrp = GroceryProvider._prices_from_text("Amul Butter\nMRP ₹310\n₹285\n8% off")
    assert price == 285
    assert mrp == 310


def test_unlabelled_price_fallback_preserves_display_order():
    price, mrp = GroceryProvider._prices_from_text("₹60\n₹75")
    assert price == 60
    assert mrp == 75


def test_deduplication_prefers_organic_listing_for_the_same_url():
    provider = object.__new__(BlinkitProvider)
    sponsored = RawListing(platform="blinkit", title="Maggi Masala", size_text="70 g", price=Decimal("14"), sponsored=True, product_url="https://blinkit.com/prn/maggi", raw_text="sponsored", fetched_at=datetime.now(timezone.utc))
    organic = sponsored.model_copy(update={"sponsored": False})
    result = provider._dedupe([sponsored, organic])
    assert result == [organic]


@pytest.mark.asyncio
async def test_malformed_card_is_skipped_without_dropping_valid_cards():
    """Regression test for provider-level per-card isolation."""
    provider = object.__new__(BlinkitProvider)
    provider.blocked = False
    provider.ready = True
    provider.lock = asyncio.Lock()
    provider.last_error = None

    class Field:
        async def fill(self, value):
            return None

    class Page:
        url = "https://blinkit.com/search"

        async def wait_for_timeout(self, milliseconds):
            return None

    async def ensure_page():
        return Page()

    async def open_search():
        return Field()

    async def extract_cards():
        return ["broken", "valid"]

    async def parse_card(card):
        if card == "broken":
            raise ValueError("unexpected card shape")
        return RawListing(platform="blinkit", title="Maggi Masala", size_text="70 g", price=Decimal("14"), raw_text="Maggi Masala 70 g ₹14", fetched_at=datetime.now(timezone.utc))

    provider._ensure_page = ensure_page
    provider._open_search = open_search
    provider._wait_for_search_results = extract_cards
    provider._parse_card = parse_card
    provider._dedupe = lambda listings: listings

    results = await BlinkitProvider.search(provider, "maggi")
    assert [item.title for item in results] == ["Maggi Masala"]
    assert "Card parse skipped" in provider.last_error


@pytest.mark.asyncio
async def test_blinkit_uses_visible_editable_search_input_without_launcher_click():
    provider = object.__new__(BlinkitProvider)

    class Page:
        url = "https://blinkit.com/"

    field = AsyncMock()
    provider._ensure_page = AsyncMock(return_value=Page())
    provider._visible_editable_search_input = AsyncMock(return_value=field)
    provider._stable_search_bar_parent = AsyncMock(return_value=None)
    provider._homepage_search_launcher = AsyncMock()

    result = await BlinkitProvider._open_search(provider)

    assert result is field
    provider._homepage_search_launcher.assert_not_awaited()


@pytest.mark.asyncio
async def test_blinkit_opens_homepage_launcher_then_uses_editable_search_input():
    provider = object.__new__(BlinkitProvider)

    class Page:
        url = "https://blinkit.com/"

    launcher = AsyncMock()
    field = AsyncMock()
    provider._ensure_page = AsyncMock(return_value=Page())
    provider._visible_editable_search_input = AsyncMock(return_value=None)
    provider._stable_search_bar_parent = AsyncMock(return_value=None)
    provider._homepage_search_launcher = AsyncMock(return_value=launcher)
    provider._wait_for_editable_search_input = AsyncMock(return_value=field)
    provider._capture_search_state = AsyncMock()

    result = await BlinkitProvider._open_search(provider)

    assert result is field
    launcher.click.assert_awaited_once()
    provider._wait_for_editable_search_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_blinkit_search_fills_requested_query_after_opening_search_ui():
    provider = object.__new__(BlinkitProvider)

    class Page:
        url = "https://blinkit.com/search"

    field = AsyncMock()
    parsed = RawListing(platform="blinkit", title="Maggi Masala", size_text="70 g", price=Decimal("14"), raw_text="Maggi Masala", fetched_at=datetime.now(timezone.utc))
    provider._ensure_page = AsyncMock(return_value=Page())
    provider._open_search = AsyncMock(return_value=field)
    provider._wait_for_search_results = AsyncMock(return_value=["card"])
    provider._parse_card = AsyncMock(return_value=parsed)
    provider._dedupe = lambda listings: listings

    result = await BlinkitProvider._search_unlocked(provider, "Maggi")

    field.fill.assert_awaited_once_with("Maggi")
    assert result == [parsed]


@pytest.mark.asyncio
async def test_blinkit_prefers_stable_search_bar_parent_over_animated_child():
    provider = object.__new__(BlinkitProvider)

    class Page:
        pass

    stable_parent = AsyncMock()
    provider._ensure_page = AsyncMock(return_value=Page())
    provider._stable_search_bar_parent = AsyncMock(return_value=stable_parent)

    result = await BlinkitProvider._homepage_search_launcher(provider)

    assert result is stable_parent
    provider._stable_search_bar_parent.assert_awaited_once()


@pytest.mark.asyncio
async def test_blinkit_uses_an_already_open_location_modal_without_clicking_opener():
    provider = object.__new__(BlinkitProvider)

    class Page:
        async def wait_for_timeout(self, milliseconds):
            return None

    field = AsyncMock()
    suggestion = AsyncMock()
    provider._ensure_page = AsyncMock(return_value=Page())
    provider._visible_location_input = AsyncMock(return_value=field)
    provider._click_location_opener = AsyncMock()
    provider._wait_for_location_input = AsyncMock()
    provider._wait_for_dtu_suggestion = AsyncMock(return_value=suggestion)

    await BlinkitProvider._set_dtu_location(provider)

    field.fill.assert_awaited_once_with("Delhi Technological University")
    provider._click_location_opener.assert_not_awaited()
    provider._wait_for_location_input.assert_not_awaited()
    suggestion.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_blinkit_clicks_opener_only_when_no_modal_input_exists():
    provider = object.__new__(BlinkitProvider)

    class Page:
        async def wait_for_timeout(self, milliseconds):
            return None

    field = AsyncMock()
    suggestion = AsyncMock()
    provider._ensure_page = AsyncMock(return_value=Page())
    provider._visible_location_input = AsyncMock(return_value=None)
    provider._click_location_opener = AsyncMock()
    provider._wait_for_location_input = AsyncMock(return_value=field)
    provider._wait_for_dtu_suggestion = AsyncMock(return_value=suggestion)

    await BlinkitProvider._set_dtu_location(provider)

    provider._click_location_opener.assert_awaited_once()
    provider._wait_for_location_input.assert_awaited_once()
    field.fill.assert_awaited_once_with("Delhi Technological University")


def test_instamart_block_detection_requires_explicit_block_phrase():
    assert InstamartProvider._block_phrase("Request Blocked\nYour request looks automated and has been blocked.") == "Your request looks automated and has been blocked"
    assert InstamartProvider._block_phrase("Your request is being processed") is None


@pytest.mark.asyncio
async def test_instamart_block_diagnostics_write_expected_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = object.__new__(InstamartProvider)

    class Page:
        url = "https://www.swiggy.com/instamart"

        async def title(self):
            return "Request Blocked"

        async def screenshot(self, path, full_page):
            from pathlib import Path
            Path(path).write_bytes(b"png")

        async def content(self):
            return "<html><body>Request Blocked</body></html>"

    provider._ensure_page = AsyncMock(return_value=Page())
    diagnostics = await InstamartProvider._capture_block_diagnostics(provider, "Request Blocked", "Request Blocked\nUseful block details")

    assert (tmp_path / diagnostics["body"]).exists()
    assert (tmp_path / diagnostics["screenshot"]).exists()
    assert (tmp_path / diagnostics["html"]).exists()
    assert "Block phrase: Request Blocked" in (tmp_path / diagnostics["body"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_blinkit_parses_card_with_numeric_id_and_line_clamp():
    provider = object.__new__(BlinkitProvider)
    provider.home_url = "https://blinkit.com/"

    class FakeLocator:
        def __init__(self, text="", count_val=0, is_vis=True, src=None):
            self._text = text
            self._count = count_val
            self._vis = is_vis
            self._src = src

        async def count(self):
            return self._count

        async def is_visible(self):
            return self._vis

        async def inner_text(self):
            return self._text

        async def get_attribute(self, attr):
            if attr == "src":
                return self._src
            return None

        @property
        def first(self):
            return self

    class FakeCard:
        async def inner_text(self):
            return "8 mins\nMaggi Spicy Cheesy Cup Noodles\n71.5 g\n₹65\nADD"

        async def get_attribute(self, attr):
            if attr == "id":
                return "764551"
            if attr == "href":
                return None
            return None

        def locator(self, selector):
            if "tw-line-clamp-2" in selector:
                return FakeLocator("Maggi Spicy Cheesy Cup Noodles", count_val=1)
            if "tw-line-clamp-1" in selector:
                return FakeLocator("71.5 g", count_val=1)
            if "tw-line-through" in selector:
                return FakeLocator(count_val=0)
            if "a[href" in selector:
                return FakeLocator(count_val=0)
            if "ad_without_bg" in selector or "sponsored" in selector or "Ad" in selector:
                return FakeLocator(count_val=0)
            if "img" in selector:
                return FakeLocator(count_val=1, src="https://cdn.grofers.com/product.png")
            return FakeLocator(count_val=0)

    listing = await BlinkitProvider._parse_card(provider, FakeCard())
    assert listing.title == "Maggi Spicy Cheesy Cup Noodles"
    assert listing.size_text == "71.5 g"
    assert listing.price == Decimal("65")
    assert listing.mrp is None
    assert listing.provider_id == "764551"
    assert listing.product_url == "https://blinkit.com/prn/maggi-spicy-cheesy-cup-noodles/prid/764551"
    assert listing.availability == "available"
    assert listing.image_url == "https://cdn.grofers.com/product.png"
    assert not listing.sponsored


@pytest.mark.asyncio
async def test_blinkit_parses_discounted_card_with_mrp_and_offer():
    provider = object.__new__(BlinkitProvider)
    provider.home_url = "https://blinkit.com/"

    class FakeLocator:
        def __init__(self, text="", count_val=0, is_vis=True, src=None):
            self._text = text
            self._count = count_val
            self._vis = is_vis
            self._src = src

        async def count(self):
            return self._count

        async def is_visible(self):
            return self._vis

        async def inner_text(self):
            return self._text

        async def get_attribute(self, attr):
            if attr == "src":
                return self._src
            return None

        @property
        def first(self):
            return self

    class FakeCard:
        async def inner_text(self):
            return "12%\nOFF\n8 mins\nMaggi 2 Minutes Instant Noodles\n420 g\n₹79\n₹90\nADD"

        async def get_attribute(self, attr):
            if attr == "id":
                return "352315"
            return None

        def locator(self, selector):
            if "tw-line-clamp-2" in selector:
                return FakeLocator("Maggi 2 Minutes Instant Noodles", count_val=1)
            if "tw-line-clamp-1" in selector:
                return FakeLocator("420 g", count_val=1)
            if "tw-line-through" in selector:
                return FakeLocator("₹90", count_val=1)
            if "a[href" in selector:
                return FakeLocator(count_val=0)
            if "img" in selector:
                return FakeLocator(count_val=1, src="https://cdn.grofers.com/maggi.png")
            return FakeLocator(count_val=0)

    listing = await BlinkitProvider._parse_card(provider, FakeCard())
    assert listing.title == "Maggi 2 Minutes Instant Noodles"
    assert listing.size_text == "420 g"
    assert listing.price == Decimal("79")
    assert listing.mrp == Decimal("90")
    assert listing.offer_text == "12% OFF"
    assert listing.provider_id == "352315"
    assert listing.availability == "available"
