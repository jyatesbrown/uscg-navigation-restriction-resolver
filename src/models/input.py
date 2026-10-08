from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..geo.geometry import geodesic_length_nm
from ..normalization.categories import ALL_CATEGORIES, Category

DEFAULT_RADIUS_NM = 5.0
MIN_RADIUS_NM, MAX_RADIUS_NM = 0.1, 50.0
DEFAULT_CORRIDOR_NM = 1.0
MIN_CORRIDOR_NM, MAX_CORRIDOR_NM = 0.1, 25.0
MAX_ROUTE_POINTS = 200
MAX_ROUTE_NM = 1500.0
MAX_BBOX_DEGREES = 10.0
MIN_ROUTE_NM = 0.01


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.south >= self.north:
            raise ValueError("bbox south must be less than north")
        if self.west >= self.east:
            raise ValueError("bbox west must be less than east (boxes crossing the antimeridian are not supported)")
        if self.north - self.south > MAX_BBOX_DEGREES or self.east - self.west > MAX_BBOX_DEGREES:
            raise ValueError(f"bbox may span at most {MAX_BBOX_DEGREES:g} degrees of latitude and longitude")
        return self


class ActorInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    point: Position | None = None
    radius_nm: float | None = Field(default=None, alias="radiusNm", ge=MIN_RADIUS_NM, le=MAX_RADIUS_NM)
    route: list[Position] | None = None
    corridor_nm: float | None = Field(default=None, alias="corridorNm", ge=MIN_CORRIDOR_NM, le=MAX_CORRIDOR_NM)
    bbox: BBox | None = None
    at_time: datetime | None = Field(default=None, alias="atTime")
    categories: list[Category] | None = None

    @field_validator("at_time")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("atTime must include a timezone, e.g. 2026-10-08T16:00:00Z")
        return v.astimezone(UTC) if v else None

    @field_validator("categories")
    @classmethod
    def _dedupe(cls, v: list[Category] | None) -> list[Category] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("categories must not be empty when provided")
        return [c for c in ALL_CATEGORIES if c in set(v)]

    @model_validator(mode="after")
    def _one_mode(self) -> Self:
        modes = [m for m in ("point", "route", "bbox") if getattr(self, m) is not None]
        if len(modes) != 1:
            raise ValueError("provide exactly one of point, route or bbox")
        if self.radius_nm is not None and self.point is None:
            raise ValueError("radiusNm applies only to point queries")
        if self.corridor_nm is not None and self.route is None:
            raise ValueError("corridorNm applies only to route queries")
        if self.route is not None:
            if not 2 <= len(self.route) <= MAX_ROUTE_POINTS:
                raise ValueError(f"route must have between 2 and {MAX_ROUTE_POINTS} points")
            length = geodesic_length_nm([(p.lon, p.lat) for p in self.route])
            if length < MIN_ROUTE_NM:
                raise ValueError("route has zero length")
            if length > MAX_ROUTE_NM:
                raise ValueError(f"route is longer than {MAX_ROUTE_NM:g} nautical miles")
            if any(abs(a.lon - b.lon) > 180 for a, b in zip(self.route, self.route[1:], strict=False)):
                raise ValueError("route segments crossing the antimeridian are not supported")
        return self

    @property
    def query_type(self) -> str:
        return "point" if self.point else "route" if self.route else "bbox"

    @property
    def requested_categories(self) -> list[Category]:
        return list(self.categories or ALL_CATEGORIES)
