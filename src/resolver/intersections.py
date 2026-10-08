from __future__ import annotations

from datetime import datetime
from typing import Any

import shapely
from shapely import ops
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from ..geo.geometry import QueryArea
from ..models.output import EffectiveWindow, Notice, NoticeSource, Relationship
from ..normalization.categories import Category
from ..normalization.dates import epoch_ms_to_dt, iso, validity
from ..sources.navcen import DatasetResult, feature_dates, record_id, record_title

VALIDITY_ORDER = {"active": 0, "upcoming": 1, "unknown": 2}


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _local(area: QueryArea, geom: dict[str, Any]) -> BaseGeometry | None:
    try:
        g = shape(geom)
    except (ValueError, TypeError, AttributeError, IndexError):
        return None
    if g.is_empty:
        return None
    lg = area.project(g)
    return lg if lg.is_valid else lg.buffer(0)


def match(area: QueryArea, results: list[DatasetResult], at: datetime) -> tuple[list[Notice], int]:
    """Return notices intersecting the search area (expired excluded) and the expired-excluded count."""
    seen: set[tuple[Category, Any]] = set()
    notices: list[Notice] = []
    expired = 0
    for res in results:
        for feat in res.features:
            props = feat["properties"]
            key = (res.category, record_id(props))
            if key in seen:
                continue
            geom = _local(area, feat["geometry"])
            if geom is None or not geom.intersects(area.search_area):
                continue
            seen.add(key)
            start, end = feature_dates(props)
            state = validity(start, end, at)
            if state == "expired":
                expired += 1
                continue
            touches = geom.intersects(area.query_geometry)
            dist = 0.0 if touches else round(area.geodesic_distance_nm(area.query_geometry, geom), 3)
            pos = None
            if area.route_line is not None:
                line = area.route_line
                if touches:
                    coords = shapely.get_coordinates(line.intersection(geom))
                    along = min(line.project(Point(c)) for c in coords) if len(coords) else 0.0
                else:
                    along = line.project(ops.nearest_points(line, geom)[0])
                pos = round(along / line.length, 3)
            notices.append(
                Notice(
                    msi_uid=record_id(props),
                    category=res.category,
                    native_category=props.get("SUB_CATEGORY") or props.get("ATON_GROUP"),
                    native_type=props.get("TYPE") or props.get("TC_STATUS"),
                    title=record_title(props),
                    waterway_name=props.get("WATERWAY_NAME"),
                    coast_guard_district=_int(props.get("ATU")),
                    record_status=props.get("STATUS") or props.get("MSI_STATUS"),
                    validity=state,
                    effective_window=EffectiveWindow(start=iso(start), end=iso(end)),
                    geometry=feat["geometry"],
                    relationship_to_query=Relationship(
                        intersects_query_geometry=touches,
                        within_search_area=True,
                        minimum_distance_nm=dist,
                        route_position=pos,
                    ),
                    official_text=props.get("DESCRIPTION"),
                    source=NoticeSource(
                        dataset=res.dataset,
                        dataset_url=res.url,
                        record_created=iso(epoch_ms_to_dt(props.get("CREATE_DATE"))),
                        record_modified=iso(epoch_ms_to_dt(props.get("MODIFIED_DATE"))),
                    ),
                )
            )
    if area.type == "route":
        notices.sort(key=lambda n: (n.relationship_to_query.route_position, VALIDITY_ORDER[n.validity], n.category))
    else:
        notices.sort(key=lambda n: (n.relationship_to_query.minimum_distance_nm, VALIDITY_ORDER[n.validity]))
    return notices, expired
