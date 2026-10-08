from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from ..billing import billing_decision
from ..geo.geometry import QueryArea, bbox_area, point_area, route_area
from ..models.input import DEFAULT_CORRIDOR_NM, DEFAULT_RADIUS_NM, ActorInput
from ..models.output import Coverage, DatasetStatus, QueryInfo, QueryResult, Summary
from ..normalization.categories import ALL_CATEGORIES
from ..normalization.dates import iso
from ..sources.navcen import INDEX_URL, Cache, fetch_categories, fetch_index
from ..utils.errors import SourceError
from ..utils.http import create_client
from .intersections import match

SOURCE_ID = "USCG_NAVCEN_MSI"


@dataclass
class Outcome:
    result: QueryResult
    elapsed_ms: float


def build_area(inp: ActorInput) -> QueryArea:
    if inp.point:
        return point_area(inp.point.lon, inp.point.lat, inp.radius_nm or DEFAULT_RADIUS_NM)
    if inp.route:
        return route_area([(p.lon, p.lat) for p in inp.route], inp.corridor_nm or DEFAULT_CORRIDOR_NM)
    assert inp.bbox
    b = inp.bbox
    return bbox_area(b.south, b.west, b.north, b.east)


def invalid_input(message: str, checked_at: str) -> QueryResult:
    return QueryResult(
        status="invalid_input",
        checked_at=checked_at,
        query=QueryInfo(at_time=checked_at),
        coverage=Coverage(complete_for_requested_layers=False),
        summary=Summary(),
        errors=[message],
        billing=billing_decision("invalid_input", 0),
    )


async def resolve(inp: ActorInput, client: httpx.AsyncClient, now: datetime, cache: Cache | None = None) -> QueryResult:
    checked_at = iso(now)
    at = inp.at_time or now
    area = build_area(inp)
    cats = inp.requested_categories
    query = QueryInfo(
        type=area.type,
        at_time=iso(at),
        radius_nm=(inp.radius_nm or DEFAULT_RADIUS_NM) if inp.point else None,
        corridor_nm=(inp.corridor_nm or DEFAULT_CORRIDOR_NM) if inp.route else None,
        route_length_nm=round(area.route_length_nm, 2) if area.route_length_nm else None,
        point_count=len(inp.route) if inp.route else None,
        categories_requested=cats,
    )
    try:
        index = await fetch_index(client)
    except SourceError as exc:
        failure = DatasetStatus(dataset="fileIndexNew", url=INDEX_URL, status=exc.state.value)
        return QueryResult(
            status="source_unavailable",
            checked_at=checked_at,
            query=query,
            coverage=Coverage(
                categories_requested=cats,
                categories_failed=cats,
                complete_for_requested_layers=False,
                source_failures=[failure],
                datasets=[failure],
            ),
            summary=Summary(),
            errors=["NAVCEN MSI file index could not be retrieved; no layers were checked."],
            billing=billing_decision("source_unavailable", 0),
        )
    results = await fetch_categories(client, cats, index, cache)
    statuses = [
        DatasetStatus(
            category=r.category,
            dataset=r.dataset,
            url=r.url,
            status=r.state.value,
            published_at=r.published_at,
            feature_count=len(r.features) if r.state == "success" else None,
            from_cache=r.from_cache,
        )
        for r in results
    ]
    failed = [c for c in cats if any(r.category == c and r.state != "success" for r in results)]
    checked = [c for c in cats if c not in failed]
    notices, expired = match(area, [r for r in results if r.state == "success"], at)
    status = "success" if not failed else "partial" if checked else "source_unavailable"
    by_cat = {c: sum(1 for n in notices if n.category == c) for c in ALL_CATEGORIES}
    summary = Summary(
        matched_notice_count=len(notices),
        active_count=sum(n.validity == "active" for n in notices),
        upcoming_count=sum(n.validity == "upcoming" for n in notices),
        unknown_validity_count=sum(n.validity == "unknown" for n in notices),
        expired_excluded_count=expired,
        categories_matched=[c for c, k in by_cat.items() if k],
        by_category={c: k for c, k in by_cat.items() if c in cats},
    )
    return QueryResult(
        status=status,
        checked_at=checked_at,
        query=query,
        coverage=Coverage(
            official_sources_checked=[SOURCE_ID] if checked else [],
            categories_requested=cats,
            categories_checked=checked,
            categories_failed=failed,
            complete_for_requested_layers=not failed,
            source_failures=[s for s in statuses if s.status != "success"],
            datasets=statuses,
            features_skipped=sum(r.skipped for r in results),
        ),
        summary=summary,
        notices=notices,
        errors=[f"{s.dataset}: {s.status}" for s in statuses if s.status != "success"],
        billing=billing_decision(status, len(notices)),
    )


async def run_query(
    inp: ActorInput, *, client: httpx.AsyncClient | None = None, now: datetime | None = None, cache: Cache | None = None
) -> Outcome:
    start = time.perf_counter()
    now = now or datetime.now(UTC)
    if client is None:
        async with create_client() as c:
            result = await resolve(inp, c, now, cache)
    else:
        result = await resolve(inp, client, now, cache)
    return Outcome(result, (time.perf_counter() - start) * 1000)
