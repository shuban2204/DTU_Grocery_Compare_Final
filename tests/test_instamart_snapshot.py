from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.providers.base import ProviderError
from app.providers.instamart_snapshot import InstamartSnapshotProvider
from app.services.search_service import SearchService


class BlockedInstamart:
    blocked = True

    async def search(self, query: str):
        raise ProviderError("Instamart blocked this browser session")


class LiveBlinkit:
    blocked = False

    async def search(self, query: str):
        return []


@pytest.mark.asyncio
async def test_snapshot_provider_loads_manual_snapshot(tmp_path):
    (tmp_path / "maggi.json").write_text(json.dumps({
        "query": "Maggi",
        "location": "Delhi Technological University",
        "captured_at": "2026-09-11T23:50:00+05:30",
        "source": "manual_snapshot",
        "products": [{"title": "MAGGI 2-Minute Masala Noodles", "size": "70 g", "price": "14", "mrp": "15", "availability": "available"}],
    }), encoding="utf-8")
    provider = InstamartSnapshotProvider(tmp_path)
    await provider.initialize()

    listings = await provider.search("Maggi")

    assert provider.ready is True
    assert listings[0].title == "MAGGI 2-Minute Masala Noodles"
    assert str(listings[0].price) == "14"
    assert provider.last_snapshot_info["available"] is True


@pytest.mark.asyncio
async def test_snapshot_provider_reports_missing_query_without_inventing_products(tmp_path):
    provider = InstamartSnapshotProvider(tmp_path)
    await provider.initialize()

    listings = await provider.search("Milk")

    assert listings == []
    assert provider.last_snapshot_info["available"] is False
    assert provider.last_snapshot_info["message"] == "Instamart data unavailable for this query."


@pytest.mark.asyncio
async def test_blocked_live_instamart_uses_manual_snapshot_metadata(tmp_path):
    (tmp_path / "maggi.json").write_text(json.dumps({
        "query": "Maggi",
        "location": "Delhi Technological University",
        "captured_at": "2026-09-11T23:50:00+05:30",
        "source": "manual_snapshot",
        "products": [{"title": "MAGGI 2-Minute Masala Noodles", "size": "70 g", "price": "14", "availability": "available"}],
    }), encoding="utf-8")
    snapshot = InstamartSnapshotProvider(tmp_path)
    await snapshot.initialize()
    service = SearchService({"blinkit": LiveBlinkit(), "instamart": BlockedInstamart()}, instamart_snapshot=snapshot)

    response = await service.search("Maggi")

    instamart = response["providers"]["instamart"]
    assert instamart["data_source"] == "manual_snapshot"
    assert instamart["captured_at"].isoformat().startswith("2026-09-11T23:50:00")
    assert len(response["unmatched"]["instamart"]) == 1


def test_ui_contains_explicit_manual_snapshot_label():
    script = (Path("app/static/app.js")).read_text(encoding="utf-8")
    assert "manual_snapshot" in script
    assert "live automated retrieval unavailable" in script


@pytest.mark.asyncio
async def test_blocked_instamart_missing_snapshot_query_reports_unavailable(tmp_path):
    # When Instamart is blocked and no snapshot exists for this query,
    # the search service must report it as unavailable without inventing fake products.
    snapshot = InstamartSnapshotProvider(tmp_path)
    await snapshot.initialize()
    service = SearchService({"blinkit": LiveBlinkit(), "instamart": BlockedInstamart()}, instamart_snapshot=snapshot)

    response = await service.search("UnknownItemQuery")

    instamart = response["providers"]["instamart"]
    assert instamart["status"] == "blocked"
    assert instamart["data_source"] == "manual_snapshot"
    assert instamart["captured_at"] is None
    assert "unavailable" in instamart["message"].lower()
    assert response["unmatched"]["instamart"] == []

