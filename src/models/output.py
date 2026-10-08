from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ..normalization.categories import Category
from ..normalization.dates import Validity

SCHEMA_VERSION = "1.0"
ResultStatus = Literal["success", "partial", "source_unavailable", "invalid_input"]
DatasetState = Literal["success", "unavailable", "timeout", "invalid_format", "not_queried"]

SCOPE_NOTE = (
    "Zero matches means no matching records were found in the official datasets successfully checked. "
    "It does not establish that hazards or restrictions are absent. This is official-notice "
    "information, not navigational advice: consult official charts, current Local and Broadcast Notices "
    "to Mariners, VHF broadcasts and applicable Coast Guard instructions."
)
NOT_COVERED = [
    "Broadcast Notices to Mariners (BNM) are not checked in this version.",
    "NAVCEN MSI records without geometry, Light List data, bridge notices and aids-to-navigation discrepancies.",
    "Non-USCG sources (NOAA charts, NGA NAVAREA warnings, AIS, weather, tides).",
]


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class QueryInfo(_Model):
    type: Literal["point", "route", "bbox"] | None = None
    at_time: str
    radius_nm: float | None = None
    corridor_nm: float | None = None
    route_length_nm: float | None = None
    point_count: int | None = None
    categories_requested: list[Category] = Field(default_factory=list)


class EffectiveWindow(_Model):
    start: str | None = Field(None, description="BEGIN_DATE from NAVCEN (UTC). Null when NAVCEN gives none.")
    end: str | None = Field(None, description="END_DATE from NAVCEN (UTC). Null = not stated (open-ended or unknown).")


class Relationship(_Model):
    intersects_query_geometry: bool = Field(
        description="Feature touches the point, the route line itself, or the bbox."
    )
    within_search_area: bool = Field(description="Feature intersects the radius circle, route corridor or bbox.")
    minimum_distance_nm: float = Field(description="Geodesic distance from the query geometry; 0 when intersecting.")
    route_position: float | None = Field(
        None, description="Approximate fraction (0-1) of the supplied route length where the notice is nearest."
    )


class NoticeSource(_Model):
    agency: str = "U.S. Coast Guard"
    system: str = "NAVCEN Maritime Safety Information"
    source_type: str = "Local Notice to Mariners geospatial record"
    dataset: str
    dataset_url: str
    app_url: str = "https://www.navcen.uscg.gov/msi"
    record_created: str | None = None
    record_modified: str | None = None


class Notice(_Model):
    msi_uid: int | str = Field(description="NAVCEN MSI_UID (LNM_UID for temporary changes).")
    category: Category
    native_category: str | None = Field(None, description="NAVCEN SUB_CATEGORY (or ATON_GROUP for temporary changes).")
    native_type: str | None = None
    title: str
    waterway_name: str | None = None
    coast_guard_district: int | None = None
    record_status: str | None = Field(None, description="NAVCEN STATUS field verbatim (e.g. Approved).")
    validity: Validity = Field(description="Computed from the effective window at query.atTime; unknown if no dates.")
    effective_window: EffectiveWindow
    geometry: dict[str, Any] = Field(description="Official GeoJSON geometry (WGS84).")
    relationship_to_query: Relationship
    official_text: str | None = Field(None, description="NAVCEN DESCRIPTION verbatim.")
    source: NoticeSource


class DatasetStatus(_Model):
    category: Category | None = None
    dataset: str
    url: str
    status: DatasetState
    published_at: str | None = None
    feature_count: int | None = None
    from_cache: bool = False


class Coverage(_Model):
    official_sources_checked: list[str] = Field(default_factory=list)
    categories_requested: list[Category] = Field(default_factory=list)
    categories_checked: list[Category] = Field(
        default_factory=list, description="Categories whose every listed dataset file loaded and validated."
    )
    categories_failed: list[Category] = Field(default_factory=list)
    complete_for_requested_layers: bool
    source_failures: list[DatasetStatus] = Field(default_factory=list)
    datasets: list[DatasetStatus] = Field(default_factory=list)
    features_skipped: int = 0
    not_covered: list[str] = Field(default_factory=lambda: list(NOT_COVERED))


class Summary(_Model):
    matched_notice_count: int = 0
    active_count: int = 0
    upcoming_count: int = 0
    unknown_validity_count: int = 0
    expired_excluded_count: int = 0
    categories_matched: list[Category] = Field(default_factory=list)
    by_category: dict[str, int] = Field(default_factory=dict)


class Billing(_Model):
    billable: bool
    event_name: str | None = None
    reason: str


class QueryResult(_Model):
    schema_version: str = SCHEMA_VERSION
    status: ResultStatus
    checked_at: str
    query: QueryInfo
    coverage: Coverage
    summary: Summary
    notices: list[Notice] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    scope_note: str = SCOPE_NOTE
    billing: Billing
