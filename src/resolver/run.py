from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from ..billing import billing_decision
from ..geo.geometry import QueryArea, bbox_area, point_area, route_area
from ..models.input import DEFAULT_CORRIDOR_NM, DEFAULT_RADIUS_NM, ActorInput
from ..models.output import CategoryCoverage, Coverage, DatasetStatus, QueryInfo, QueryResult, Summary
from ..normalization.categories import ALL_CATEGORIES, SINGULAR, geometry_kind
from ..normalization.dates import iso
from ..sources.navcen import INDEX_URL, Cache, fetch_categories, fetch_index
from ..utils.errors import SourceError, SourceState
from ..utils.http import create_client
from .intersections import match

SOURCE_ID = "USCG_NAVCEN_MSI"


def _join(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def coverage_note(categories: dict[str, CategoryCoverage], states: dict[str, str], matched: int) -> str | None:
    gaps = {c: v for c, v in categories.items() if v.status != "complete"}
    if not gaps:
        return None
    sentences = []
    for cat, cov in gaps.items():
        label = SINGULAR[cat]
        if cov.checked:
            kinds = _join([geometry_kind(d) for d in cov.checked])
            sentences.append(f"{label[0].upper() + label[1:]} {kinds} datasets were checked successfully.")
        reasons = []
        if cov.listed_but_not_published:
            verb = "that dataset was" if len(cov.listed_but_not_published) == 1 else "those datasets were"
            reasons.append(
                f"the NAVCEN index lists {_join(cov.listed_but_not_published)}, "
                f"but {verb} not published at retrieval time"
            )
        if cov.unavailable:
            reasons.append(
                ("the official dataset file " if len(cov.unavailable) == 1 else "the official dataset files ")
                + _join([f"{d} ({states[d]})" for d in cov.unavailable])
                + " could not be retrieved or validated"
            )
        missing = cov.listed_but_not_published + cov.unavailable
        consequence = (
            f"{_join([geometry_kind(d) for d in missing])}-based {label} coverage is incomplete"
            if cov.checked
            else f"no {label} dataset could be checked"
        )
        text = "; ".join(reasons)
        sentences.append(f"{text[0].upper() + text[1:]}, so {consequence}.")
    if matched:
        sentences.append(
            "The returned notices come from datasets that were checked; records in the datasets not checked "
            "could not be evaluated."
        )
    else:
        sentences.append(
            "No matches were found in the datasets successfully checked, but coverage is incomplete: this does not "
            "mean no records exist in the datasets that were not checked."
        )
    return " ".join(sentences)


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
                categories_unavailable=cats,
                categories_failed=cats,
                categories={c: CategoryCoverage(status="unavailable") for c in cats},
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
    unpublished_state = SourceState.LISTED_BUT_NOT_PUBLISHED
    categories: dict[str, CategoryCoverage] = {}
    for c in cats:
        rs = [r for r in results if r.category == c]
        ok = [r.dataset for r in rs if r.state == "success"]
        lbnp = [r.dataset for r in rs if r.state == unpublished_state]
        bad = [r.dataset for r in rs if r.state not in ("success", unpublished_state)]
        state = "complete" if not lbnp and not bad else "partial" if ok else "unavailable"
        categories[c] = CategoryCoverage(status=state, checked=ok, unavailable=bad, listed_but_not_published=lbnp)
    failed = [c for c in cats if categories[c].unavailable]
    incomplete = [c for c in cats if categories[c].listed_but_not_published]
    unavailable_cats = [c for c in cats if categories[c].status == "unavailable"]
    partially = [c for c in cats if categories[c].status == "partial"]
    checked = [c for c in cats if c not in unavailable_cats]
    complete = all(v.status == "complete" for v in categories.values())
    unpublished = [s for s in statuses if s.status == unpublished_state]
    failures = [s for s in statuses if s.status not in ("success", unpublished_state)]
    notices, expired = match(area, [r for r in results if r.state == "success"], at)
    any_success = any(r.state == "success" for r in results)
    status = "success" if complete else "partial" if any_success else "source_unavailable"
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
            categories_partially_checked=partially,
            categories_unavailable=unavailable_cats,
            categories_failed=failed,
            categories_incomplete=incomplete,
            categories=categories,
            complete_for_requested_layers=complete,
            coverage_note=coverage_note(categories, {s.dataset: s.status for s in statuses}, len(notices)),
            source_failures=failures,
            unpublished_datasets=unpublished,
            datasets=statuses,
            features_skipped=sum(r.skipped for r in results),
        ),
        summary=summary,
        notices=notices,
        errors=[f"{s.dataset}: {s.status}" for s in failures]
        + [f"{s.dataset}: listed in NAVCEN file index but not published (HTTP 404); not checked" for s in unpublished],
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
