from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import CACHE_TTL_SECONDS, STALE_TTL_SECONDS
from app.models import RawListing


@dataclass
class CacheEntry:
    data: list[RawListing]
    fetched_at: datetime

    @property
    def age(self) -> timedelta:
        return datetime.now(timezone.utc) - self.fetched_at

    @property
    def fresh(self) -> bool:
        return self.age.total_seconds() <= CACHE_TTL_SECONDS

    @property
    def usable_stale(self) -> bool:
        return self.age.total_seconds() <= STALE_TTL_SECONDS


class ProviderCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], CacheEntry] = {}
        self._last_refresh: dict[tuple[str, str], datetime] = {}

    def get(self, provider: str, query: str) -> CacheEntry | None:
        return self._entries.get((provider, query))

    def put(self, provider: str, query: str, data: list[RawListing]) -> CacheEntry:
        fetched_at = max((item.fetched_at for item in data), default=datetime.now(timezone.utc))
        entry = CacheEntry(data=data, fetched_at=fetched_at)
        self._entries[(provider, query)] = entry
        return entry

    def refresh_allowed(self, provider: str, query: str, cooldown_seconds: int) -> bool:
        last = self._last_refresh.get((provider, query))
        now = datetime.now(timezone.utc)
        if last and (now - last).total_seconds() < cooldown_seconds:
            return False
        self._last_refresh[(provider, query)] = now
        return True
