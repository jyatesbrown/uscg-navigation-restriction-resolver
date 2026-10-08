"""Manual live check against NAVCEN (not run in CI). Prints one line per case."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.input import ActorInput
from src.resolver.run import run_query

CASES = {
    "nyc_bbox": {"bbox": {"south": 40.4, "west": -74.3, "north": 40.9, "east": -73.7}},
    "new_rochelle_point": {"point": {"lat": 40.89, "lon": -73.78}, "radiusNm": 2},
    "houston_route": {"route": [{"lat": 29.31, "lon": -94.70}, {"lat": 29.73, "lon": -95.03}], "corridorNm": 1},
    "vandenberg_space_route": {"route": [{"lat": 34.40, "lon": -120.50}, {"lat": 34.80, "lon": -121.00}]},
    "canaveral_route": {"route": [{"lat": 28.30, "lon": -80.40}, {"lat": 28.60, "lon": -80.30}], "corridorNm": 2},
    "open_atlantic_zero": {"point": {"lat": 35.0, "lon": -60.0}},
    "kaneohe_d14": {"point": {"lat": 21.46, "lon": -157.76}, "radiusNm": 3},
}


async def main() -> None:
    names = sys.argv[1:] or list(CASES)
    for name in names:
        out = await run_query(ActorInput.model_validate(CASES[name]))
        r = out.result
        cats = {k: v for k, v in r.summary.by_category.items() if v}
        fails = [f"{f.dataset}:{f.status}" for f in r.coverage.source_failures]
        print(
            f"{name}: {r.status} matched={r.summary.matched_notice_count} {json.dumps(cats)} "
            f"failures={fails} billable={r.billing.billable} {out.elapsed_ms:.0f}ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
