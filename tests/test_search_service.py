from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import RawListing
from app.providers.base import ProviderError
from app.services import search_service as search_module
from app.services.matcher import PairMatch
from app.services.normalizer import normalize_listing
from app.services.search_service import SearchService


def listing(platform: str, title: str = "Amul Salted Butter", size: str = "500 g", price: str = "100", availability: str = "unknown") -> RawListing:
    return RawListing(platform=platform, title=title, size_text=size, price=Decimal(price), availability=availability, raw_text=f"{title} {size}", fetched_at=datetime.now(timezone.utc))


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.enrich_calls = 0

    async def search(self, query: str):
        self.calls += 1
        response = self.responses.pop(0) if self.responses else []
        if response == "timeout":
            await asyncio.sleep(1)
        if isinstance(response, Exception):
            raise response
        return response

    async def enrich(self, item):
        self.enrich_calls += 1
        return item


def service(blinkit_responses, instamart_responses) -> tuple[SearchService, FakeProvider, FakeProvider]:
    blinkit = FakeProvider(blinkit_responses)
    instamart = FakeProvider(instamart_responses)
    return SearchService({"blinkit": blinkit, "instamart": instamart}), blinkit, instamart


@pytest.mark.asyncio
async def test_one_provider_failure_keeps_other_provider_results():
    subject, _, _ = service([[listing("blinkit")]], [ProviderError("provider failed")])
    response = await subject.search("butter")
    assert response["providers"]["blinkit"]["status"] == "ok"
    assert response["providers"]["instamart"]["status"] == "error"
    assert len(response["unmatched"]["blinkit"]) == 1


@pytest.mark.asyncio
async def test_provider_timeout_is_reported_without_crashing(monkeypatch):
    monkeypatch.setattr(search_module, "PROVIDER_TIMEOUT_SECONDS", 0.01)
    subject, _, _ = service(["timeout"], [[listing("instamart")]])
    response = await subject.search("butter")
    assert response["providers"]["blinkit"]["status"] == "timeout"
    assert response["providers"]["instamart"]["status"] == "ok"


@pytest.mark.asyncio
async def test_cache_hit_and_manual_refresh_throttle():
    subject, blinkit, instamart = service([[listing("blinkit")], [listing("blinkit", price="99")]], [[listing("instamart")], [listing("instamart", price="98")]])
    await subject.search("butter")
    cached = await subject.search("butter")
    assert cached["providers"]["blinkit"]["source"] == "cache"
    assert (blinkit.calls, instamart.calls) == (1, 1)
    await subject.search("butter", refresh=True)
    throttled = await subject.search("butter", refresh=True)
    assert (blinkit.calls, instamart.calls) == (2, 2)
    assert "Refresh throttled" in throttled["providers"]["blinkit"]["message"]


@pytest.mark.asyncio
async def test_stale_fallback_and_expired_cache():
    subject, blinkit, instamart = service([[listing("blinkit")], ProviderError("live failed"), ProviderError("live failed")], [[listing("instamart")], ProviderError("live failed"), ProviderError("live failed")])
    await subject.search("butter")
    for name in ("blinkit", "instamart"):
        subject.cache.get(name, "butter").fetched_at = datetime.now(timezone.utc) - timedelta(seconds=181)
    stale = await subject.search("butter", refresh=True)
    assert stale["providers"]["blinkit"]["status"] == "stale"
    assert stale["providers"]["instamart"]["status"] == "stale"
    for name in ("blinkit", "instamart"):
        subject.cache.get(name, "butter").fetched_at = datetime.now(timezone.utc) - timedelta(seconds=1801)
    subject.cache._last_refresh.clear()
    expired = await subject.search("butter", refresh=True)
    assert expired["providers"]["blinkit"]["status"] == "error"
    assert expired["providers"]["instamart"]["status"] == "error"


@pytest.mark.asyncio
async def test_empty_provider_result_is_a_valid_empty_search():
    subject, _, _ = service([[]], [[]])
    response = await subject.search("unknown item")
    assert response["providers"]["blinkit"]["status"] == "ok"
    assert response["matches"] == []
    assert response["unmatched"] == {"blinkit": [], "instamart": []}


@pytest.mark.asyncio
async def test_comparable_pricing_does_not_rank_an_unavailable_listing():
    subject, _, _ = service(
        [[listing("blinkit", "Lay's Magic Masala", "52 g", "20")]],
        [[listing("instamart", "Lay's Magic Masala", "48 g", "18", "unavailable")]],
    )
    response = await subject.search("lays")
    assert response["matches"][0]["relationship"] == "comparable"
    assert "winner" not in response["matches"][0]["pricing"]


@pytest.mark.asyncio
async def test_comparable_pricing_uses_normalized_unit_price_when_available():
    subject, _, _ = service(
        [[listing("blinkit", "Lay's Magic Masala", "52 g", "20")]],
        [[listing("instamart", "Lay's Magic Masala", "48 g", "18")]],
    )
    response = await subject.search("lays", quantity=3)
    pricing = response["matches"][0]["pricing"]
    assert pricing["winner"] == "instamart"
    assert pricing["blinkit_unit"]["suffix"] == "/100 g"


@pytest.mark.asyncio
async def test_detail_enrichment_is_capped_to_two_ambiguous_pairs():
    subject, blinkit, instamart = service([[]], [[]])
    pairs = []
    for index in range(3):
        b = normalize_listing(listing("blinkit", f"Amul Butter Variant {index}", "500 g"))
        i = normalize_listing(listing("instamart", f"Amul Butter Pack {index}", "480 g"))
        pairs.append(PairMatch("comparable", 80, b, i, ["ambiguous"]))
    await subject._enrich_ambiguous(pairs)
    assert blinkit.enrich_calls == 2
    assert instamart.enrich_calls == 2


@pytest.mark.asyncio
async def test_obvious_exact_match_does_not_open_detail_pages():
    subject, blinkit, instamart = service([[listing("blinkit")]], [[listing("instamart")]])
    response = await subject.search("butter")
    assert response["matches"][0]["relationship"] == "exact"
    assert blinkit.enrich_calls == 0
    assert instamart.enrich_calls == 0


@pytest.mark.asyncio
async def test_missing_size_triggers_enrichment_path():
    # Listing with missing size (size=None) should trigger enrichment
    subject, blinkit, instamart = service(
        [[listing("blinkit", "Coca-Cola Soft Drink", size=None)]],
        [[listing("instamart", "Coca-Cola Soft Drink", size="750 ml")]],
    )
    response = await subject.search("coca cola")
    assert len(response["matches"]) == 1
    # Enrichment was triggered for the candidate with missing size
    assert blinkit.enrich_calls == 1
    assert instamart.enrich_calls == 1


@pytest.mark.asyncio
async def test_ambiguous_manual_snapshot_does_not_invoke_blocked_live_instamart_enrich(tmp_path):
    import json
    from app.providers.instamart_snapshot import InstamartSnapshotProvider

    # Create a manual snapshot with missing size
    (tmp_path / "coca_cola.json").write_text(json.dumps({
        "query": "Coca Cola",
        "location": "Delhi Technological University",
        "captured_at": "2026-09-11T23:50:00+05:30",
        "source": "manual_snapshot",
        "products": [{"title": "Coca-Cola Soft Drink", "size": None, "price": "40", "availability": "available"}],
    }), encoding="utf-8")

    snapshot = InstamartSnapshotProvider(tmp_path)
    await snapshot.initialize()

    class BlockedLiveInstamart:
        blocked = True
        enrich_calls = 0

        async def search(self, query: str):
            raise ProviderError("Instamart blocked this browser session")

        async def enrich(self, item):
            self.enrich_calls += 1
            return item

    class LiveBlinkit:
        enrich_calls = 0

        async def search(self, query: str):
            return [listing("blinkit", "Coca-Cola Soft Drink", size=None, price="40")]

        async def enrich(self, item):
            self.enrich_calls += 1
            return item

    live_blinkit = LiveBlinkit()
    blocked_instamart = BlockedLiveInstamart()

    subject = SearchService(
        {"blinkit": live_blinkit, "instamart": blocked_instamart},
        instamart_snapshot=snapshot,
    )

    response = await subject.search("Coca Cola")
    assert len(response["matches"]) == 1
    assert response["providers"]["instamart"]["data_source"] == "manual_snapshot"
    # Blinkit detail enrichment still runs normally
    assert live_blinkit.enrich_calls == 1
    # Blocked live Instamart enrich must NOT be invoked for manual snapshot listings
    assert blocked_instamart.enrich_calls == 0


