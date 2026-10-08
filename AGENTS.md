# AGENTS.md

Apify Actor (Python 3.12) that checks one point, user-supplied route or bounding box against the official
USCG NAVCEN Maritime Safety Information GeoJSON layers and emits exactly one dataset record.
Deterministic only: no LLMs, no browsers, no third-party sources.

## Layout
- `src/main.py` Actor entry point (input, push record, charge `navigation-area-check` once).
- `src/resolver/run.py` orchestration; `src/resolver/intersections.py` spatial match + ordering.
- `src/sources/navcen.py` one general adapter for every layer in `fileIndexNew.json`; `cache.py` TTL cache.
- `src/geo/geometry.py` local azimuthal-equidistant projection, nm buffers, geodesic distances.
- `src/normalization/` categories (layer families) and dates/validity.
- `src/billing.py` pure billing decision.

## Commands
```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest                                   # fixtures + respx, no network
python scripts/live_smoke_test.py        # live NAVCEN (manual only)
python scripts/export_dataset_schema.py  # regenerate .actor/dataset_schema.json
```

## Rules
- Tests never hit the network; fixtures in `tests/fixtures/navcen/` are real NAVCEN records.
  Do not assert on notices remaining live; shift `atTime` instead.
- A failed or malformed layer must make the result `partial`/`source_unavailable`, never zero matches.
- Never emit safety verdicts (`safe`, `clear`, `routeIsSafe`, ...). Preserve official text verbatim.
