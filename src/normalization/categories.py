"""NAVCEN MSI layer families mapped to normalized categories.

Each family is published as up to three geometry variants (`{prefix}_`, `{prefix}Line_`, `{prefix}Poly_`),
each split into numbered pages listed in `fileIndexNew.json`.
"""

from __future__ import annotations

from typing import Literal

Category = Literal[
    "safety_zone",
    "hazard_to_navigation",
    "marine_construction",
    "marine_event",
    "naval_activity",
    "space_operation",
    "temporary_change",
    "tess_advisory",
    "msib",
]

LAYER_FAMILIES: dict[Category, tuple[str, ...]] = {
    "safety_zone": ("safeZone_", "safeZoneLine_", "safeZonePoly_"),
    "hazard_to_navigation": ("hazNav_", "hazNavLine_", "hazNavPoly_"),
    "marine_construction": ("marCon_", "marConLine_", "marConPoly_"),
    "marine_event": ("marEvent_", "marEventLine_", "marEventPoly_"),
    "naval_activity": ("navalAct_", "navalActLine_", "navalActPoly_"),
    "space_operation": ("spaceOps_", "spaceOpsLine_", "spaceOpsPoly_"),
    "temporary_change": ("tmpChange_",),
    "tess_advisory": ("tessAdv_", "tessAdvLine_", "tessAdvPoly_"),
    "msib": ("msib_", "msibLine_", "msibPoly_"),
}

ALL_CATEGORIES: tuple[Category, ...] = tuple(LAYER_FAMILIES)

LABELS: dict[Category, str] = {
    "safety_zone": "Safety Zones",
    "hazard_to_navigation": "Hazards to Navigation",
    "marine_construction": "Marine Construction",
    "marine_event": "Marine Events",
    "naval_activity": "Naval Activity",
    "space_operation": "Space Operations",
    "temporary_change": "Temporary Changes (aids to navigation)",
    "tess_advisory": "TESS Advisories",
    "msib": "Marine Safety Information Bulletins (geospatial)",
}
