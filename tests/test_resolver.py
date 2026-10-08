from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import httpx
import pytest
from shapely.geometry import shape

from src.models.input import ActorInput
from src.resolver.run import invalid_input, run_query
from src.sources.navcen import BASE, INDEX_URL

from .conftest import NOW, feature, index_fixture, load


async def run(client, payload, **kw):
    return (await run_query(ActorInput.model_validate(payload), client=client, now=NOW, **kw)).result


def uids(result):
    return {n.msi_uid for n in result.notices}


# --- spatial ---------------------------------------------------------------


async def test_point_inside_safety_zone(navcen, client):
    r = await run(client, {"point": {"lat": 40.8895, "lon": -73.7825}, "radiusNm": 0.5})
    assert r.status == "success"
    assert {6236, 7532} <= uids(r)
    n = next(n for n in r.notices if n.msi_uid == 6236)
    assert n.category == "safety_zone"
    assert n.relationship_to_query.within_search_area
    assert n.relationship_to_query.route_position is None
    assert n.official_text == feature("safeZonePoly_1", 6236)["properties"]["DESCRIPTION"]
    assert n.source.dataset_url == BASE + "safeZonePoly_1.geojson"


async def test_point_feature_radius_boundary(navcen, client):
    # hazNav 58 at 39.4741 N, -74.2949; query 2 nm due north
    q = {"lat": 39.4741 + 2 / 60, "lon": -74.2949}
    near = await run(client, {"point": q, "radiusNm": 3, "categories": ["hazard_to_navigation"]})
    far = await run(client, {"point": q, "radiusNm": 1.5, "categories": ["hazard_to_navigation"]})
    n = next(n for n in near.notices if n.msi_uid == 58)
    assert n.relationship_to_query.minimum_distance_nm == pytest.approx(2.0, abs=0.02)
    assert not n.relationship_to_query.intersects_query_geometry
    assert 58 not in uids(far)


async def test_point_to_route_distance_and_corridor(navcen, client):
    # hazNav 61 at 38.6825 N, -75.1001; route runs 1.5 nm east of it
    lon = -75.1001 + 1.5 / (60 * 0.78084)
    route = [{"lat": 38.60, "lon": lon}, {"lat": 38.76, "lon": lon}]
    wide = await run(client, {"route": route, "corridorNm": 2, "categories": ["hazard_to_navigation"]})
    narrow = await run(client, {"route": route, "corridorNm": 1, "categories": ["hazard_to_navigation"]})
    n = next(n for n in wide.notices if n.msi_uid == 61)
    assert n.relationship_to_query.minimum_distance_nm == pytest.approx(1.5, abs=0.03)
    assert n.relationship_to_query.route_position == pytest.approx(0.516, abs=0.01)
    assert 61 not in uids(narrow)


async def test_route_crossing_polygon_and_ordering(navcen, client):
    p = shape(feature("safeZonePoly_1", 6236)["geometry"]).representative_point()
    route = [{"lat": p.y, "lon": p.x - 0.05}, {"lat": p.y, "lon": p.x + 0.05}]
    r = await run(client, {"route": route, "corridorNm": 0.2})
    n = next(n for n in r.notices if n.msi_uid == 6236)
    assert n.relationship_to_query.intersects_query_geometry
    assert n.relationship_to_query.minimum_distance_nm == 0
    positions = [n.relationship_to_query.route_position for n in r.notices]
    assert positions == sorted(positions)


async def test_line_feature_intersection(navcen, client):
    coords = feature("marConLine_1", 38555)["geometry"]["coordinates"]
    lon, lat = coords[len(coords) // 2]
    r = await run(client, {"point": {"lat": lat, "lon": lon}, "radiusNm": 0.1})
    assert 38555 in uids(r)


async def test_bbox_query(navcen, client):
    r = await run(client, {"bbox": {"south": 42.4, "west": -71.0, "north": 42.6, "east": -70.7}})
    assert {52676, 35689, 36841} <= uids(r)
    assert all(n.relationship_to_query.minimum_distance_nm == 0 for n in r.notices)


# --- temporal --------------------------------------------------------------


async def test_validity_classes_and_expired_exclusion(navcen, client):
    q = {"point": {"lat": 34.6667, "lon": -120.62}, "radiusNm": 5, "categories": ["space_operation"]}
    now = await run(client, q)
    later = await run(client, {**q, "atTime": "2026-10-15T00:00:00Z"})
    before = await run(client, {**q, "atTime": "2026-09-01T00:00:00Z"})
    assert {n.validity for n in now.notices} == {"active"}
    assert 54442 not in uids(later)
    assert later.summary.expired_excluded_count >= 1
    assert before.summary.upcoming_count == before.summary.matched_notice_count > 0


async def test_unknown_validity_when_no_dates(navcen, client):
    r = await run(
        client, {"point": {"lat": 25.9015, "lon": -80.1316}, "radiusNm": 0.5, "categories": ["temporary_change"]}
    )
    assert r.summary.matched_notice_count == 2
    assert r.summary.unknown_validity_count == 2
    assert all(n.effective_window.start is None and n.effective_window.end is None for n in r.notices)
    assert r.notices[0].title.startswith("Biscayne Bay Buoy")


# --- coverage, source semantics and billing --------------------------------

OPEN_OCEAN = {"point": {"lat": 35.0, "lon": -60.0}, "radiusNm": 5}


async def test_success_zero_matches_is_billable_and_complete(navcen, client):
    r = await run(client, OPEN_OCEAN)
    assert r.status == "success"
    assert r.summary.matched_notice_count == 0
    assert r.coverage.complete_for_requested_layers
    assert r.coverage.source_failures == []
    assert r.billing.billable


@pytest.mark.parametrize(
    ("response", "state"),
    [
        (httpx.Response(503), "unavailable"),
        (httpx.Response(200, content=b"<html>maintenance</html>"), "invalid_format"),
        (httpx.Response(200, json={"type": "Feature"}), "invalid_format"),
        (httpx.Response(200, json={"type": "FeatureCollection", "features": [{"properties": {}}]}), "invalid_format"),
        (httpx.TimeoutException("slow"), "timeout"),
    ],
)
async def test_failed_layer_is_never_zero_hazards(navcen, client, response, state, monkeypatch):
    monkeypatch.setattr("src.utils.http.BACKOFF_BASE_SECONDS", 0)
    route = navcen.get(BASE + "safeZonePoly_1.geojson")
    route.mock(side_effect=response) if isinstance(response, Exception) else route.mock(return_value=response)
    failed = await run(client, OPEN_OCEAN)
    ok = await run(client, {**OPEN_OCEAN, "categories": ["hazard_to_navigation"]})
    assert failed.status == "partial"
    assert not failed.coverage.complete_for_requested_layers
    assert failed.coverage.categories_failed == ["safety_zone"]
    assert [f.status for f in failed.coverage.source_failures] == [state]
    assert not failed.billing.billable
    assert failed.to_record() != ok.to_record()
    assert ok.status == "success"


async def test_index_listed_404_is_listed_but_not_published(navcen, client):
    idx = index_fixture()
    idx["safeZoneLine_"]["counter"] = 1
    navcen.get(url__startswith=INDEX_URL).mock(return_value=httpx.Response(200, json=idx))
    navcen.get(BASE + "safeZoneLine_1.geojson").mock(return_value=httpx.Response(404))
    r = await run(client, OPEN_OCEAN)
    assert r.status == "partial"
    assert r.coverage.categories_incomplete == ["safety_zone"]
    assert r.coverage.categories_failed == []
    assert "safety_zone" not in r.coverage.categories_checked
    assert r.coverage.source_failures == []
    assert [d.dataset for d in r.coverage.unpublished_datasets] == ["safeZoneLine_1"]
    assert next(d for d in r.coverage.datasets if d.dataset == "safeZoneLine_1").feature_count is None
    assert not r.coverage.complete_for_requested_layers
    assert "does not mean no records exist" in r.coverage.coverage_note
    assert not r.billing.billable
    assert not FORBIDDEN.search(json.dumps(r.to_record()))
    other = await run(client, {**OPEN_OCEAN, "categories": ["hazard_to_navigation"]})
    assert other.status == "success"
    assert other.billing.billable


async def test_partial_with_matches_is_billable(navcen, client):
    navcen.get(BASE + "hazNav_1.geojson").mock(return_value=httpx.Response(500))
    r = await run(client, {"point": {"lat": 40.8895, "lon": -73.7825}, "radiusNm": 0.5})
    assert r.status == "partial"
    assert r.summary.matched_notice_count > 0
    assert r.billing.billable


async def test_empty_valid_dataset_is_success(navcen, client):
    navcen.get(BASE + "safeZonePoly_1.geojson").mock(
        return_value=httpx.Response(200, json={"type": "FeatureCollection", "features": []})
    )
    r = await run(client, OPEN_OCEAN)
    assert r.status == "success"
    assert next(d for d in r.coverage.datasets if d.dataset == "safeZonePoly_1").feature_count == 0


async def test_feature_missing_geometry_is_skipped_and_counted(navcen, client):
    data = load("safeZonePoly_1.geojson")
    data["features"][0]["geometry"] = None
    navcen.get(BASE + "safeZonePoly_1.geojson").mock(return_value=httpx.Response(200, json=data))
    r = await run(client, {"point": {"lat": 40.8895, "lon": -73.7825}, "radiusNm": 0.5})
    assert r.status == "success"
    assert r.coverage.features_skipped == 1


async def test_index_failure_is_source_unavailable(navcen, client, monkeypatch):
    monkeypatch.setattr("src.utils.http.BACKOFF_BASE_SECONDS", 0)
    navcen.get(url__startswith=INDEX_URL).mock(return_value=httpx.Response(502))
    r = await run(client, OPEN_OCEAN)
    assert r.status == "source_unavailable"
    assert not r.billing.billable
    assert r.coverage.categories_checked == []


async def test_malformed_index_is_controlled(navcen, client):
    navcen.get(url__startswith=INDEX_URL).mock(return_value=httpx.Response(200, json={"foo": {"counter": 1}}))
    r = await run(client, OPEN_OCEAN)
    assert r.status == "source_unavailable"
    assert r.coverage.source_failures[0].status == "invalid_format"


async def test_unknown_index_prefixes_ignored_and_duplicate_pages_deduplicated(navcen, client):
    idx = index_fixture()
    idx["brandNewLayer_"] = {"counter": 3, "timestamp": 1}
    idx["msibPoly_"]["counter"] = 2
    navcen.get(url__startswith=INDEX_URL).mock(return_value=httpx.Response(200, json=idx))
    navcen.get(BASE + "msibPoly_2.geojson").mock(return_value=httpx.Response(200, json=load("msibPoly_1.geojson")))
    r = await run(client, {"point": {"lat": 29.73, "lon": -95.03}, "radiusNm": 5, "categories": ["msib"]})
    assert r.status == "success"
    assert len([n for n in r.notices if n.msi_uid == 27034]) == 1


# --- safety language ---------------------------------------------------------

FORBIDDEN = re.compile(r"\b(safe|clear|unrestricted|hazard-free|approved for transit)\b", re.IGNORECASE)


async def test_zero_match_record_makes_no_safety_claim(navcen, client):
    r = await run(client, OPEN_OCEAN)
    text = json.dumps(r.to_record())
    assert not FORBIDDEN.search(text)
    for key in ("routeIsSafe", "safeToTransit", "navigationClear", "noHazardsExist"):
        assert key not in text
    assert "not navigational advice" in r.scope_note


def test_invalid_input_record_is_not_billable():
    r = invalid_input("route has zero length", datetime(2026, 10, 7, tzinfo=UTC).isoformat())
    assert r.status == "invalid_input"
    assert not r.billing.billable


# --- cache -------------------------------------------------------------------


class MemoryStore:
    def __init__(self):
        self.data = {}

    async def get_value(self, key):
        return self.data.get(key)

    async def set_value(self, key, value):
        self.data[key] = value


async def test_cache_reused_only_for_same_publication(navcen, client):
    from src.sources.cache import KeyValueCache

    cache = KeyValueCache(MemoryStore())
    first = await run(client, OPEN_OCEAN, cache=cache)
    second = await run(client, OPEN_OCEAN, cache=cache)
    assert not any(d.from_cache for d in first.coverage.datasets)
    assert all(d.from_cache for d in second.coverage.datasets)
    idx = index_fixture()
    idx["safeZonePoly_"]["timestamp"] += 60
    navcen.get(url__startswith=INDEX_URL).mock(return_value=httpx.Response(200, json=idx))
    third = await run(client, OPEN_OCEAN, cache=cache)
    assert not next(d for d in third.coverage.datasets if d.dataset == "safeZonePoly_1").from_cache


async def test_expired_cache_entry_not_used(navcen, client):
    from src.sources.cache import KeyValueCache

    cache = KeyValueCache(MemoryStore(), ttl=-1)
    await run(client, OPEN_OCEAN, cache=cache)
    again = await run(client, OPEN_OCEAN, cache=cache)
    assert not any(d.from_cache for d in again.coverage.datasets)
