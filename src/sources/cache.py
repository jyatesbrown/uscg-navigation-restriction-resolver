"""Shared-layer cache in a named Apify key-value store.

A cached copy is reused only while it is younger than the TTL *and* the NAVCEN file index still reports
the same publication timestamp, so a refreshed layer is never answered from stale data.
"""

from __future__ import annotations

import re
import time
from typing import Any

TTL_SECONDS = 15 * 60
STORE_NAME = "uscg-msi-layer-cache"


class KeyValueCache:
    def __init__(self, store: Any, ttl: float = TTL_SECONDS) -> None:
        self.store, self.ttl = store, ttl

    @staticmethod
    def _key(dataset: str) -> str:
        return re.sub(r"[^a-zA-Z0-9!\-_.'()]", "_", dataset)

    async def get(self, dataset: str, published: int) -> list[dict[str, Any]] | None:
        try:
            entry = await self.store.get_value(self._key(dataset))
        except Exception:
            return None
        if not isinstance(entry, dict) or entry.get("published") != published:
            return None
        if time.time() - float(entry.get("fetchedAt", 0)) > self.ttl:
            return None
        feats = entry.get("features")
        return feats if isinstance(feats, list) else None

    async def put(self, dataset: str, published: int, features: list[dict[str, Any]]) -> None:
        try:
            await self.store.set_value(
                self._key(dataset), {"published": published, "fetchedAt": time.time(), "features": features}
            )
        except Exception:
            return
