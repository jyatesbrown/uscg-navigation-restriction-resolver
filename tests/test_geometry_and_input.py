from __future__ import annotations

import pytest
from pydantic import ValidationError
from shapely.geometry import shape

from src.geo.geometry import point_area, route_area
from src.models.input import ActorInput

from .conftest import feature


def test_point_buffer_is_true_nautical_miles_not_degrees():
    for lat in (0.0, 45.0, 64.0):
        area = point_area(-150.0, lat, 10).search_area.area / 1852**2
        assert area == pytest.approx(314.16, rel=0.01)


def test_route_corridor_area_matches_length_times_width():
    a = route_area([(-80.0, 27.0), (-80.0, 28.0)], 2)
    assert a.route_length_nm == pytest.approx(60.0, rel=0.01)
    assert a.search_area.area / 1852**2 == pytest.approx(60 * 4 + 3.1416 * 4, rel=0.02)


def test_polygon_crossing_route_has_zero_distance():
    poly = shape(feature("safeZonePoly_1", 6236)["geometry"])
    p = poly.representative_point()
    a = route_area([(p.x - 0.05, p.y), (p.x + 0.05, p.y)], 0.5)
    local = a.project(poly)
    assert local.intersects(a.query_geometry)


@pytest.mark.parametrize(
    "payload",
    [
        {"point": {"lat": 95, "lon": 0}},
        {"point": {"lat": 10, "lon": -181}},
        {"route": [{"lat": 27.0, "lon": -80.0}, {"lat": 27.0, "lon": -80.0}]},
        {"route": [{"lat": 27.0, "lon": -80.0}]},
        {"route": [{"lat": 51.0, "lon": 179.5}, {"lat": 51.2, "lon": -179.5}]},
        {"bbox": {"south": 27, "west": -79, "north": 29, "east": -81}},
        {"bbox": {"south": 20, "west": -90, "north": 35, "east": -80}},
        {"point": {"lat": 27, "lon": -80}, "bbox": {"south": 27, "west": -81, "north": 29, "east": -79}},
        {},
        {"point": {"lat": 27, "lon": -80}, "radiusNm": 0},
        {"point": {"lat": 27, "lon": -80}, "radiusNm": 51},
        {"point": {"lat": 27, "lon": -80}, "corridorNm": 2},
        {"point": {"lat": 27, "lon": -80}, "categories": ["bogus"]},
        {"point": {"lat": 27, "lon": -80}, "atTime": "2026-10-08T16:00:00"},
    ],
)
def test_invalid_inputs_rejected(payload):
    with pytest.raises(ValidationError):
        ActorInput.model_validate(payload)


def test_defaults_and_category_order():
    inp = ActorInput.model_validate({"point": {"lat": 27, "lon": -80}, "categories": ["msib", "safety_zone", "msib"]})
    assert inp.radius_nm is None
    assert inp.requested_categories == ["safety_zone", "msib"]
