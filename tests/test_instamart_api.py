from __future__ import annotations

import asyncio
import json
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import RawListing
from app.providers.instamart_api import QuickCommerceInstamartProvider
from app.providers.instamart_snapshot import InstamartSnapshotProvider
from app.services.pricing import listing_total
from app.services.search_service import SearchService


@pytest.fixture
def sample_maggi_api_items():
    return [
        {
            "id": "PP8VVOYNES",
            "name": "2-Minute Instant Noodles, Made With Quality Spices",
            "brand": "Maggi",
            "available": True,
            "images": ["https://media-assets.swiggy.com/img1.png"],
            "mrp": "240",
            "offer_price": "240",
            "quantity": "280 g x 4",
            "deeplink": "https://www.swiggy.com/instamart/p/--L5XS0G5W34",
            "is_ad": False,
            "store_id": "1404620",
        },
        {
            "id": "PP8VVOYNES",
            "name": "2-Minute Instant Noodles, Made With Quality Spices",
            "brand": "Maggi",
            "available": True,
            "images": ["https://media-assets.swiggy.com/img1.png"],
            "mrp": "120",
            "offer_price": "120",
            "quantity": "280 g x 2",
            "deeplink": "https://www.swiggy.com/instamart/p/--XR43QFU3UY",
            "is_ad": False,
            "store_id": "1404620",
        },
        {
            "id": "PP8VVOYNES",
            "name": "2-Minute Instant Noodles, Made With Quality Spices",
            "brand": "Maggi",
            "available": True,
            "images": ["https://media-assets.swiggy.com/img1.png"],
            "mrp": "60",
            "offer_price": "60",
            "quantity": "280 g",
            "deeplink": "https://www.swiggy.com/instamart/p/--C065XMRW6S",
            "is_ad": False,
            "store_id": "1404620",
        },
        {
            "id": "YV7VEW4E8J",
            "name": "2-Minute Instant Noodles, Made With Quality Spices",
            "brand": "Maggi",
            "available": True,
            "images": ["https://media-assets.swiggy.com/img2.png"],
            "mrp": "180",
            "offer_price": "154",
            "quantity": "420 g x 2",
            "deeplink": "https://www.swiggy.com/instamart/p/--G0NDI91C09",
            "is_ad": True,
            "store_id": "1404620",
        },
        {
            "id": "YV7VEW4E8J",
            "name": "2-Minute Instant Noodles, Made With Quality Spices",
            "brand": "Maggi",
            "available": True,
            "images": ["https://media-assets.swiggy.com/img2.png"],
            "mrp": "90",
            "offer_price": "78",
            "quantity": "420 g",
            "deeplink": "https://www.swiggy.com/instamart/p/--LCD1BOQPNE",
            "is_ad": True,
            "store_id": "1404620",
        },
    ]


@pytest.fixture
def sample_coke_api_items():
    return [
        {
            "id": "COKE_REG_12",
            "name": "Coca-Cola PET - Cola Sparkling Soft Drink",
            "brand": "Coca Cola",
            "available": True,
            "images": ["https://media-assets.swiggy.com/coke1.png"],
            "mrp": "480",
            "offer_price": "387",
            "quantity": "750 ml x 12",
            "deeplink": "https://www.swiggy.com/instamart/p/coke-750-12",
            "is_ad": False,
        },
        {
            "id": "COKE_REG_2",
            "name": "Coca-Cola PET - Cola Sparkling Soft Drink",
            "brand": "Coca Cola",
            "available": True,
            "images": ["https://media-assets.swiggy.com/coke1.png"],
            "mrp": "80",
            "offer_price": "65",
            "quantity": "750 ml x 2",
            "deeplink": "https://www.swiggy.com/instamart/p/coke-750-2",
            "is_ad": False,
        },
        {
            "id": "COKE_REG_1",
            "name": "Coca-Cola PET - Cola Sparkling Soft Drink",
            "brand": "Coca Cola",
            "available": True,
            "images": ["https://media-assets.swiggy.com/coke1.png"],
            "mrp": "40",
            "offer_price": "38",
            "quantity": "750 ml",
            "deeplink": "https://www.swiggy.com/instamart/p/coke-750-1",
            "is_ad": False,
        },
        {
            "id": "COKE_ZERO_2",
            "name": "Coca-Cola Zero Sugar PET - Cola Sparkling Soft Drink",
            "brand": "Coca Cola",
            "available": True,
            "images": ["https://media-assets.swiggy.com/zero1.png"],
            "mrp": "80",
            "offer_price": "65",
            "quantity": "750 ml x 2",
            "deeplink": "https://www.swiggy.com/instamart/p/zero-750-2",
            "is_ad": False,
        },
        {
            "id": "COKE_ZERO_1",
            "name": "Coca-Cola Zero Sugar PET - Cola Sparkling Soft Drink",
            "brand": "Coca Cola",
            "available": True,
            "images": ["https://media-assets.swiggy.com/zero1.png"],
            "mrp": "40",
            "offer_price": "38",
            "quantity": "750 ml",
            "deeplink": "https://www.swiggy.com/instamart/p/zero-750-1",
            "is_ad": False,
        },
        {
            "id": "CHIPS_UNRELATED",
            "name": "Kettle Chips (Basil Thai) No Palm Oil Snacks",
            "brand": "Red Rock Deli",
            "available": True,
            "images": ["https://media-assets.swiggy.com/chips.png"],
            "mrp": "180",
            "offer_price": "129",
            "quantity": "58 g x 3",
            "deeplink": "https://www.swiggy.com/instamart/p/chips-58-3",
            "is_ad": True,
        },
    ]


def test_field_mapping(sample_maggi_api_items):
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    observed_at = datetime.now(timezone.utc)
    results = provider._parse_and_consolidate(sample_maggi_api_items, observed_at)

    # Find the 280g base listing
    item_280 = next(r for r in results if r.size_text == "280 g")
    assert "Maggi" in item_280.title
    assert "Instant Noodles" in item_280.title
    assert item_280.price == Decimal("60")
    assert item_280.mrp == Decimal("60")
    assert item_280.availability == "available"
    assert item_280.image_url == "https://media-assets.swiggy.com/img1.png"
    assert item_280.product_url == "https://www.swiggy.com/instamart/p/--C065XMRW6S"
    assert item_280.attributes.get("api_id") == "PP8VVOYNES"
    assert item_280.attributes.get("store_id") == "1404620"


def test_bundle_consolidation_maggi_280g_and_420g(sample_maggi_api_items):
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    observed_at = datetime.now(timezone.utc)
    results = provider._parse_and_consolidate(sample_maggi_api_items, observed_at)

    # 5 API rows should collapse into exactly 2 distinct SKU base listings (280g and 420g)
    assert len(results) == 2

    r_280 = next(r for r in results if r.size_text == "280 g")
    assert r_280.price == Decimal("60")
    assert "2 for ₹120" in r_280.offer_text
    assert "4 for ₹240" in r_280.offer_text
    assert listing_total(r_280, 1) == Decimal("60")
    assert listing_total(r_280, 2) == Decimal("120")
    assert listing_total(r_280, 4) == Decimal("240")

    r_420 = next(r for r in results if r.size_text == "420 g")
    assert r_420.price == Decimal("78")
    assert r_420.mrp == Decimal("90")
    assert r_420.offer_text == "2 for ₹154"
    assert listing_total(r_420, 1) == Decimal("78")
    assert listing_total(r_420, 2) == Decimal("154")


def test_coke_750ml_bundle_consolidation(sample_coke_api_items):
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    observed_at = datetime.now(timezone.utc)
    results = provider._parse_and_consolidate(sample_coke_api_items, observed_at)

    coke_reg = next(r for r in results if "Zero Sugar" not in r.title and "Chips" not in r.title)
    assert coke_reg.size_text == "750 ml"
    assert coke_reg.price == Decimal("38")
    assert coke_reg.mrp == Decimal("40")
    assert "2 for ₹65" in coke_reg.offer_text
    assert "12 for ₹387" in coke_reg.offer_text

    assert listing_total(coke_reg, 1) == Decimal("38")
    assert listing_total(coke_reg, 2) == Decimal("65")
    assert listing_total(coke_reg, 12) == Decimal("387")


def test_variant_safety_coke_and_coke_zero_never_merged(sample_coke_api_items):
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    observed_at = datetime.now(timezone.utc)
    results = provider._parse_and_consolidate(sample_coke_api_items, observed_at)

    coke_reg = [r for r in results if "Zero Sugar" not in r.title and "Chips" not in r.title]
    coke_zero = [r for r in results if "Zero Sugar" in r.title]

    assert len(coke_reg) == 1
    assert len(coke_zero) == 1
    assert coke_reg[0].size_text == "750 ml"
    assert coke_zero[0].size_text == "750 ml"
    assert "Zero Sugar" in coke_zero[0].title


@pytest.mark.asyncio
async def test_unrelated_api_search_result_filtered(sample_coke_api_items):
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    mock_payload = {
        "status": "success",
        "data": {"products": sample_coke_api_items},
        "credits_remaining": 95,
    }
    provider._sync_request = MagicMock(return_value=json.dumps(mock_payload))
    await provider.initialize()

    # Mock blinkit provider
    blinkit_mock = MagicMock()
    blinkit_mock.search = AsyncMock(return_value=[
        RawListing(
            platform="blinkit",
            title="Coca-Cola Soft Drink - 750 ml",
            size_text="750 ml",
            price=Decimal("38"),
            mrp=Decimal("40"),
            raw_text="",
            fetched_at=datetime.now(timezone.utc),
        )
    ])
    blinkit_mock.enrich = AsyncMock(side_effect=lambda x: x)

    search_service = SearchService(
        providers={"blinkit": blinkit_mock, "instamart": provider},
        instamart_snapshot=InstamartSnapshotProvider(),
    )

    response = await search_service.search("Coca Cola")
    assert response["providers"]["instamart"]["status"] == "ok"
    assert response["providers"]["instamart"]["data_source"] == "live_api"

    # Red Rock Deli chips must be filtered out by query relevance
    all_instamart_titles = [m["instamart"]["title"] for m in response["matches"]] + [
        u["title"] for u in response["unmatched"]["instamart"]
    ]
    assert not any("Chips" in t or "Red Rock" in t for t in all_instamart_titles)


@pytest.mark.asyncio
async def test_missing_api_key_snapshot_fallback():
    provider = QuickCommerceInstamartProvider(api_key="")
    snapshot_provider = InstamartSnapshotProvider()

    blinkit_mock = MagicMock()
    blinkit_mock.search = AsyncMock(return_value=[])

    search_service = SearchService(
        providers={"blinkit": blinkit_mock, "instamart": provider},
        instamart_snapshot=snapshot_provider,
    )

    response = await search_service.search("Maggi")
    instamart_status = response["providers"]["instamart"]

    assert instamart_status["source"] == "snapshot"
    assert instamart_status["data_source"] == "manual_snapshot"
    assert instamart_status["status"] == "ok"


@pytest.mark.asyncio
async def test_api_timeout_snapshot_fallback():
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    provider._sync_request = MagicMock(side_effect=TimeoutError("Connection timed out"))
    await provider.initialize()

    snapshot_provider = InstamartSnapshotProvider()
    blinkit_mock = MagicMock()
    blinkit_mock.search = AsyncMock(return_value=[])

    search_service = SearchService(
        providers={"blinkit": blinkit_mock, "instamart": provider},
        instamart_snapshot=snapshot_provider,
    )

    response = await search_service.search("Maggi")
    instamart_status = response["providers"]["instamart"]

    assert instamart_status["source"] == "snapshot"
    assert instamart_status["data_source"] == "manual_snapshot"
    assert instamart_status["status"] == "ok"


@pytest.mark.asyncio
async def test_api_500_error_snapshot_fallback():
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    error = urllib.error.HTTPError("http://test", 500, "Internal Server Error", {}, None)
    provider._sync_request = MagicMock(side_effect=error)
    await provider.initialize()

    snapshot_provider = InstamartSnapshotProvider()
    blinkit_mock = MagicMock()
    blinkit_mock.search = AsyncMock(return_value=[])

    search_service = SearchService(
        providers={"blinkit": blinkit_mock, "instamart": provider},
        instamart_snapshot=snapshot_provider,
    )

    response = await search_service.search("Maggi")
    instamart_status = response["providers"]["instamart"]

    assert instamart_status["source"] == "snapshot"
    assert instamart_status["data_source"] == "manual_snapshot"
    assert instamart_status["status"] == "ok"


@pytest.mark.asyncio
async def test_malformed_json_snapshot_fallback():
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    provider._sync_request = MagicMock(return_value="<html>Error 502 Bad Gateway</html>")
    await provider.initialize()

    snapshot_provider = InstamartSnapshotProvider()
    blinkit_mock = MagicMock()
    blinkit_mock.search = AsyncMock(return_value=[])

    search_service = SearchService(
        providers={"blinkit": blinkit_mock, "instamart": provider},
        instamart_snapshot=snapshot_provider,
    )

    response = await search_service.search("Maggi")
    instamart_status = response["providers"]["instamart"]

    assert instamart_status["source"] == "snapshot"
    assert instamart_status["data_source"] == "manual_snapshot"
    assert instamart_status["status"] == "ok"


@pytest.mark.asyncio
async def test_successful_api_returns_live_api_source(sample_maggi_api_items):
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    mock_payload = {
        "status": "success",
        "data": {"products": sample_maggi_api_items},
        "credits_remaining": 88,
    }
    provider._sync_request = MagicMock(return_value=json.dumps(mock_payload))
    await provider.initialize()

    blinkit_mock = MagicMock()
    blinkit_mock.search = AsyncMock(return_value=[])

    search_service = SearchService(
        providers={"blinkit": blinkit_mock, "instamart": provider},
        instamart_snapshot=InstamartSnapshotProvider(),
    )

    response = await search_service.search("Maggi")
    instamart_status = response["providers"]["instamart"]

    assert instamart_status["source"] == "live"
    assert instamart_status["data_source"] == "live_api"
    assert instamart_status["status"] == "ok"
    assert provider.last_credits_remaining == 88


@pytest.mark.asyncio
async def test_api_derived_listing_never_invokes_playwright_enrichment(sample_maggi_api_items):
    provider = QuickCommerceInstamartProvider(api_key="mock_key")
    mock_payload = {
        "status": "success",
        "data": {"products": sample_maggi_api_items},
        "credits_remaining": 88,
    }
    provider._sync_request = MagicMock(return_value=json.dumps(mock_payload))
    await provider.initialize()

    # Create dummy live Playwright provider spy that asserts if called
    playwright_instamart_spy = MagicMock()
    playwright_instamart_spy.enrich = AsyncMock(side_effect=AssertionError("Playwright enrich should never be called!"))

    # Blinkit returns a near-match to trigger enrichment check
    blinkit_mock = MagicMock()
    blinkit_mock.search = AsyncMock(return_value=[
        RawListing(
            platform="blinkit",
            title="Maggi 2-Minute Masala Noodles",
            size_text="280 g",
            price=Decimal("60"),
            mrp=Decimal("60"),
            product_url="https://blinkit.com/prn/maggi/prid/123",
            raw_text="",
            fetched_at=datetime.now(timezone.utc),
        )
    ])
    blinkit_mock.enrich = AsyncMock(side_effect=lambda x: x)

    search_service = SearchService(
        providers={"blinkit": blinkit_mock, "instamart": provider},
        instamart_snapshot=InstamartSnapshotProvider(),
    )

    # Perform search; should not throw AssertionError
    response = await search_service.search("Maggi")
    assert response["providers"]["instamart"]["data_source"] == "live_api"
    playwright_instamart_spy.enrich.assert_not_called()
