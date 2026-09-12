from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.config import MAX_DETAIL_PAIRS, PROVIDER_TIMEOUT_SECONDS, REFRESH_COOLDOWN_SECONDS
from app.models import NormalizedProduct, RawListing
from app.providers.base import GroceryProvider, ProviderLocationError
from app.providers.instamart_snapshot import InstamartSnapshotProvider
from app.services.cache import ProviderCache
from app.services.matcher import PairMatch, pair_products
from app.services.normalizer import is_query_relevant, normalize_listing, normalize_text
from app.services.pricing import listing_total, normalized_unit_price

logger = logging.getLogger(__name__)
SCOPE_NOTE = "Prices are snapshots of visible item-level listings. Checkout fees, coupons, memberships, payment offers and hidden cart promotions are not included. Final availability is confirmed by the provider."


class SearchService:
    def __init__(self, providers: dict[str, GroceryProvider], instamart_snapshot: InstamartSnapshotProvider | None = None):
        self.providers = providers
        self.instamart_snapshot = instamart_snapshot
        self.cache = ProviderCache()

    async def _fetch_provider(self, name: str, query: str, refresh: bool) -> tuple[list[RawListing], dict[str, Any]]:
        provider = self.providers.get(name)
        if isinstance(provider, InstamartSnapshotProvider):
            snapshot_data = await provider.search(query)
            info = provider.last_snapshot_info
            if snapshot_data:
                return snapshot_data, {
                    "status": "ok",
                    "source": "snapshot",
                    "data_source": "manual_snapshot",
                    "fetched_at": info.get("captured_at"),
                    "captured_at": info.get("captured_at"),
                    "message": "Live automated retrieval unavailable. Showing a manually captured snapshot.",
                }
            return [], {
                "status": "blocked",
                "source": "snapshot",
                "data_source": "manual_snapshot",
                "fetched_at": None,
                "captured_at": info.get("captured_at"),
                "message": "Live automated retrieval unavailable. Instamart data unavailable for this query.",
            }
        cached = self.cache.get(name, query)
        if cached and cached.fresh and not refresh:
            return cached.data, {"status": "ok", "fetched_at": cached.fetched_at, "source": "cache", "data_source": "cached_live"}
        if refresh and not self.cache.refresh_allowed(name, query, REFRESH_COOLDOWN_SECONDS):
            if cached:
                return cached.data, {"status": "ok", "fetched_at": cached.fetched_at, "source": "cache", "data_source": "cached_live", "message": "Refresh throttled; using the latest live snapshot."}
        try:
            data = await asyncio.wait_for(self.providers[name].search(query), timeout=PROVIDER_TIMEOUT_SECONDS)
            entry = self.cache.put(name, query, data)
            data_source = "live_api" if getattr(self.providers[name], "name", "") == "instamart_api" else "live"
            return data, {"status": "ok", "fetched_at": entry.fetched_at, "source": "live", "data_source": data_source}
        except asyncio.TimeoutError:
            logger.warning("%s search timed out for %r", name, query)
            if cached and cached.usable_stale:
                return cached.data, {"status": "stale", "fetched_at": cached.fetched_at, "source": "cache", "data_source": "cached_live", "message": "Live refresh timed out; showing cached live results."}
            if name == "instamart" and self.instamart_snapshot:
                snapshot_data = await self.instamart_snapshot.search(query)
                info = self.instamart_snapshot.last_snapshot_info
                if snapshot_data:
                    return snapshot_data, {
                        "status": "ok",
                        "source": "snapshot",
                        "data_source": "manual_snapshot",
                        "fetched_at": info.get("captured_at"),
                        "captured_at": info.get("captured_at"),
                        "message": "Live Instamart API timed out. Showing a manually captured snapshot.",
                    }
                return [], {
                    "status": "blocked",
                    "source": "snapshot",
                    "data_source": "manual_snapshot",
                    "fetched_at": None,
                    "captured_at": info.get("captured_at"),
                    "message": "Live Instamart API timed out and snapshot data unavailable for this query.",
                }
            return [], {"status": "timeout", "fetched_at": None, "data_source": "unavailable", "message": "Provider timed out."}
        except Exception as exc:
            logger.warning("%s search failed for %r: %s", name, query, exc)
            if cached and cached.usable_stale:
                return cached.data, {"status": "stale", "fetched_at": cached.fetched_at, "source": "cache", "data_source": "cached_live", "message": "Live refresh failed; showing cached live results."}
            if name == "instamart" and self.instamart_snapshot:
                snapshot_data = await self.instamart_snapshot.search(query)
                info = self.instamart_snapshot.last_snapshot_info
                if snapshot_data:
                    return snapshot_data, {
                        "status": "ok",
                        "source": "snapshot",
                        "data_source": "manual_snapshot",
                        "fetched_at": info.get("captured_at"),
                        "captured_at": info.get("captured_at"),
                        "message": "Live automated retrieval unavailable. Showing a manually captured snapshot.",
                    }
                return [], {
                    "status": "blocked",
                    "source": "snapshot",
                    "data_source": "manual_snapshot",
                    "fetched_at": None,
                    "captured_at": info.get("captured_at"),
                    "message": "Live automated retrieval unavailable. Instamart data unavailable for this query.",
                }
            error = "location_error" if isinstance(exc, ProviderLocationError) else "blocked" if "blocked" in str(exc).casefold() else "error"
            return [], {"status": error, "fetched_at": None, "data_source": "unavailable", "message": "Provider is temporarily unavailable."}

    @staticmethod
    def _needs_enrichment(match: PairMatch) -> bool:
        if match.score >= 88 and match.blinkit.item_amount_base is not None and match.instamart.item_amount_base is not None:
            if match.blinkit.variant_tokens == match.instamart.variant_tokens:
                return False
        if match.score >= 74:
            if match.blinkit.item_amount_base is None or match.instamart.item_amount_base is None:
                return True
            if not match.blinkit.variant_tokens or not match.instamart.variant_tokens:
                return True
        return False

    async def _enrich_ambiguous(self, pairs: list[PairMatch], instamart_no_browser: bool = False) -> tuple[list[NormalizedProduct], list[NormalizedProduct]]:
        targets = [pair for pair in pairs if self._needs_enrichment(pair)][:MAX_DETAIL_PAIRS]
        if not targets:
            return [], []

        blinkit_coros = [self.providers["blinkit"].enrich(pair.blinkit.raw) for pair in targets]
        if instamart_no_browser:
            # Do NOT invoke the blocked live Instamart browser provider when listings are from manual snapshots or live API.
            if self.instamart_snapshot:
                instamart_coros = [self.instamart_snapshot.enrich(pair.instamart.raw) for pair in targets]
            else:
                async def _noop(item: RawListing) -> RawListing:
                    return item
                instamart_coros = [_noop(pair.instamart.raw) for pair in targets]
        else:
            instamart_coros = [self.providers["instamart"].enrich(pair.instamart.raw) for pair in targets]

        outcomes = await asyncio.gather(*(blinkit_coros + instamart_coros), return_exceptions=True)
        blinkit = [normalize_listing(outcome) for outcome in outcomes[:len(targets)] if isinstance(outcome, RawListing)]
        instamart = [normalize_listing(outcome) for outcome in outcomes[len(targets):] if isinstance(outcome, RawListing)]
        return blinkit, instamart

    async def search(self, query: str, quantity: int = 1, refresh: bool = False) -> dict[str, Any]:
        normalized_query = normalize_text(query)
        outcomes = await asyncio.gather(*(self._fetch_provider(name, normalized_query, refresh) for name in ("blinkit", "instamart")))
        blinkit_raw, blinkit_status = outcomes[0]
        instamart_raw, instamart_status = outcomes[1]
        blinkit = [normalize_listing(item) for item in blinkit_raw]
        instamart = [normalize_listing(item) for item in instamart_raw]

        # Lightweight query relevance filter before matching
        blinkit = [item for item in blinkit if is_query_relevant(query, item.raw.title)]
        instamart = [item for item in instamart if is_query_relevant(query, item.raw.title)]

        pairs, unmatched_b, unmatched_i = pair_products(blinkit, instamart)

        # At most two ambiguous pairs or missing-size pairs are enriched, then matching is recomputed once.
        if blinkit_status["status"] in {"ok", "stale"} and instamart_status["status"] in {"ok", "stale"}:
            instamart_ds = instamart_status.get("data_source")
            instamart_no_browser = instamart_ds in {"manual_snapshot", "live_api"}
            enriched_b, enriched_i = await self._enrich_ambiguous(pairs, instamart_no_browser=instamart_no_browser)

            if enriched_b or enriched_i:
                by_url_b = {item.raw.product_url: item for item in enriched_b if item.raw.product_url}
                by_url_i = {item.raw.product_url: item for item in enriched_i if item.raw.product_url}
                blinkit = [by_url_b.get(item.raw.product_url, item) for item in blinkit]
                instamart = [by_url_i.get(item.raw.product_url, item) for item in instamart]
                pairs, unmatched_b, unmatched_i = pair_products(blinkit, instamart)

        return {
            "query": query,
            "quantity": quantity,
            "location": "Delhi Technological University",
            "providers": {"blinkit": blinkit_status, "instamart": instamart_status},
            "matches": [self._match_payload(pair, quantity) for pair in pairs],
            "unmatched": {"blinkit": [self._listing_payload(item, quantity) for item in unmatched_b], "instamart": [self._listing_payload(item, quantity) for item in unmatched_i]},
            "scope_note": SCOPE_NOTE,
        }

    def _listing_payload(self, product: NormalizedProduct, quantity: int) -> dict[str, Any]:
        raw = product.raw.model_dump(mode="json")
        raw["quantity_total"] = listing_total(product.raw, quantity)
        unit = normalized_unit_price(product)
        raw["unit_price"] = {"amount": unit[0], "suffix": unit[1]} if unit else None
        return raw

    def _match_payload(self, pair: PairMatch, quantity: int) -> dict[str, Any]:
        blinkit = self._listing_payload(pair.blinkit, quantity)
        instamart = self._listing_payload(pair.instamart, quantity)
        pricing: dict[str, Any] = {}
        if pair.relationship == "exact":
            left, right = blinkit["quantity_total"], instamart["quantity_total"]
            pricing.update({"blinkit_total": left, "instamart_total": right})
            if left is not None and right is not None and pair.blinkit.raw.availability != "unavailable" and pair.instamart.raw.availability != "unavailable":
                if left < right:
                    pricing.update({"winner": "blinkit", "savings": right - left})
                elif right < left:
                    pricing.update({"winner": "instamart", "savings": left - right})
                else:
                    pricing.update({"winner": "tie", "savings": 0})
        else:
            left, right = blinkit["unit_price"], instamart["unit_price"]
            if (
                left
                and right
                and left["suffix"] == right["suffix"]
                and pair.blinkit.raw.availability != "unavailable"
                and pair.instamart.raw.availability != "unavailable"
            ):
                pricing.update({"blinkit_unit": left, "instamart_unit": right})
                if left["amount"] < right["amount"]:
                    pricing["winner"] = "blinkit"
                elif right["amount"] < left["amount"]:
                    pricing["winner"] = "instamart"
                else:
                    pricing["winner"] = "tie"
        return {"relationship": pair.relationship, "score": round(pair.score, 1), "reasons": pair.reasons, "blinkit": blinkit, "instamart": instamart, "pricing": pricing}
