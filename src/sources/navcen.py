"""One general adapter for every NAVCEN MSI GeoJSON layer listed in `fileIndexNew.json`."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx

from ..normalization.categories import LAYER_FAMILIES, Category
from ..normalization.dates import epoch_ms_to_dt, iso
from ..utils.errors import SourceError, SourceState
from ..utils.http import get_json

BASE = "https://www.navcen.uscg.gov/sites/default/files/msi/"
INDEX_URL = BASE + "fileIndexNew.json"
GEOMETRY_TYPES = frozenset({"Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"})


class Cache(Protocol):
    async def get(self, dataset: str, published: int) -> list[dict[str, Any]] | None: ...
    async def put(self, dataset: str, published: int, features: list[dict[str, Any]]) -> None: ...


@dataclass
class DatasetResult:
    category: Category
    dataset: str
    url: str
    state: SourceState
    published: int | None = None
    features: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    from_cache: bool = False
    detail: str | None = None

    @property
    def published_at(self) -> str | None:
        return iso(epoch_ms_to_dt(self.published * 1000)) if self.published else None


def record_id(props: dict[str, Any]) -> Any:
    """MSI layers use MSI_UID; the aids-to-navigation temporary-change layer uses LNM_UID."""
    return props.get("MSI_UID") if props.get("MSI_UID") is not None else props.get("LNM_UID")


def record_title(props: dict[str, Any]) -> str | None:
    return props.get("TITLE") or props.get("NAME") or None


def parse_index(raw: Any) -> dict[str, tuple[int, int | None]]:
    """Return {layer prefix: (page count, published epoch seconds)}; raise on unexpected structure."""
    if not isinstance(raw, dict) or not raw:
        raise SourceError(SourceState.INVALID_FORMAT, "file index is not a non-empty object")
    out: dict[str, tuple[int, int | None]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("counter"), int) or entry["counter"] < 0:
            raise SourceError(SourceState.INVALID_FORMAT, f"file index entry {key!r} has no valid counter")
        ts = entry.get("timestamp")
        out[key] = (entry["counter"], ts if isinstance(ts, int) else None)
    known = {p for prefixes in LAYER_FAMILIES.values() for p in prefixes}
    if not known & set(out):
        raise SourceError(SourceState.INVALID_FORMAT, "file index lists none of the known MSI layers")
    return out


def validate_features(raw: Any, dataset: str) -> tuple[list[dict[str, Any]], int]:
    """Check FeatureCollection structure; drop features lacking usable geometry or identity (counted)."""
    if not isinstance(raw, dict) or raw.get("type") != "FeatureCollection" or not isinstance(raw.get("features"), list):
        raise SourceError(SourceState.INVALID_FORMAT, f"{dataset}: not a GeoJSON FeatureCollection")
    kept, skipped = [], 0
    for feat in raw["features"]:
        props = feat.get("properties") if isinstance(feat, dict) else None
        geom = feat.get("geometry") if isinstance(feat, dict) else None
        if (
            not isinstance(props, dict)
            or record_id(props) is None
            or not record_title(props)
            or not isinstance(geom, dict)
            or geom.get("type") not in GEOMETRY_TYPES
            or not geom.get("coordinates")
        ):
            skipped += 1
            continue
        kept.append({"type": "Feature", "geometry": geom, "properties": props})
    if raw["features"] and not kept:
        raise SourceError(SourceState.INVALID_FORMAT, f"{dataset}: no feature has usable geometry and identity")
    return kept, skipped


async def fetch_index(client: httpx.AsyncClient) -> dict[str, tuple[int, int | None]]:
    try:
        return parse_index(await get_json(client, INDEX_URL))
    except SourceError as exc:
        if exc.state == SourceState.NOT_FOUND:
            raise SourceError(SourceState.UNAVAILABLE, exc.detail) from exc
        raise


async def fetch_dataset(
    client: httpx.AsyncClient, category: Category, dataset: str, published: int | None, cache: Cache | None
) -> DatasetResult:
    url = BASE + dataset + ".geojson"
    if cache and published:
        cached = await cache.get(dataset, published)
        if cached is not None:
            return DatasetResult(category, dataset, url, SourceState.SUCCESS, published, cached, from_cache=True)
    try:
        features, skipped = validate_features(await get_json(client, url), dataset)
    except SourceError as exc:
        # NAVCEN's file index lists the file but it is not served; NAVCEN's own map skips it silently.
        state = SourceState.LISTED_BUT_NOT_PUBLISHED if exc.state == SourceState.NOT_FOUND else exc.state
        return DatasetResult(category, dataset, url, state, published, detail=exc.detail)
    if cache and published:
        await cache.put(dataset, published, features)
    return DatasetResult(category, dataset, url, SourceState.SUCCESS, published, features, skipped)


async def fetch_categories(
    client: httpx.AsyncClient,
    categories: list[Category],
    index: dict[str, tuple[int, int | None]],
    cache: Cache | None = None,
) -> list[DatasetResult]:
    jobs = []
    for cat in categories:
        for prefix in LAYER_FAMILIES[cat]:
            pages, published = index.get(prefix, (0, None))
            for n in range(1, pages + 1):
                jobs.append(fetch_dataset(client, cat, f"{prefix}{n}", published, cache))
    return list(await asyncio.gather(*jobs))


def feature_dates(props: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    return epoch_ms_to_dt(props.get("BEGIN_DATE")), epoch_ms_to_dt(props.get("END_DATE"))
