# Launch readiness: USCG Navigation Restriction Resolver (build 1.0.1, private)

Actor: https://console.apify.com/actors/OCbjQ4jQhPeTh9VnF (private) · 256 MB · 120 s · `LIMITED_PERMISSIONS` · Standby off
Pricing: `PAY_PER_EVENT`, `apify-actor-start` $0.00005, `navigation-area-check` $0.05 (primary), usage passthrough off.

## Competition
Apify MCP `search-actors` for the 8 required queries (notice to mariners, USCG navigation, safety zones,
navigation hazards, maritime restrictions, Coast Guard marine safety, Local Notice to Mariners, Broadcast
Notice to Mariners): no Actor resolves USCG notices spatially. Adjacent only: Panama Canal advisories, USCG
boat recalls, USCG PSIX vessel inspections, AIS/vessel and weather Actors.

## Official source feasibility
NAVCEN MSI GeoJSON (`fileIndexNew.json` + `{layer}_{n}.geojson`), no key, ~34 files / 3.2 MB / ~1,900
features. One generic adapter covers 9 categories (25 layer prefixes). Known quirks:
- `safeZoneLine_1` is listed in the index (last updated 2026-08-17) but returns HTTP 404. Reported as
  `listed_but_not_published`: not checked, not empty, coverage incomplete (owner decision).
- `tmpChange_` uses `LNM_UID`/`NAME`/`MSI_STATUS` and has no dates → validity `unknown`.
- Duplicate `msibPoly_` pages are deduplicated by record identity.
- District-wide MSIB/marine-event polygons match any query inside them (returned as published).
- BNM: no machine-readable geospatial feed; excluded from v1 and listed in `coverage.notCovered`.

## Architecture
`sources/navcen.py` (index + layer adapter, validation, controlled states) → `resolver/run.py` (concurrent
fetch, coverage, billing) → `resolver/intersections.py` (intersection, distance, route position, dedupe,
ordering) → one dataset record. Geometry in a query-centred azimuthal-equidistant projection with metric
buffers; geodesic distances on WGS84. Named-store cache (`uscg-msi-layer-cache`), short TTL, invalidated
when NAVCEN's per-layer publication timestamp changes.

## Tests
61 offline tests (fixtures are real NAVCEN records; respx mocks, no network): input validation, nm
buffers, corridors, polygon crossing, near-but-outside, point-to-route distance, antimeridian, zero-length
routes, active/upcoming/expired/unknown/open-ended, valid/empty/HTTP-failure/timeout/malformed/missing
geometry/unknown-prefix datasets, index failure, listed-but-not-published, dedupe, cache TTL and
invalidation, billing, forbidden safety wording. Ruff check/format clean.

## Platform acceptance (9 runs, build 1.0.1)

| Case | Status | Notices | Charged check | Query ms | Run s |
|---|---|---:|---:|---:|---:|
| A NYC bbox (cold) | partial | 53 | 1 | 3049 | 7.3 |
| B New Rochelle point 2 nm | partial | 2 | 1 | 693 | 5.3 |
| C Houston Ship Channel route | partial | 14 | 1 | 386 | 2.9 |
| D Vandenberg route (space ops) | partial | 5 | 1 | 752 | 6.0 |
| E Kaneohe, HI (D14) | partial | 4 | 1 | 326 | 3.4 |
| F Open Atlantic, all layers | partial | 0 | 0 | 368 | 3.0 |
| G Open Atlantic, hazards only | success | 0 | 1 | 1081 | 5.9 |
| H Zero-length route | invalid_input | 0 | 0 | – | 5.5 |
| I NYC bbox repeat (cached) | partial | 53 | 1 | 441 | 4.3 |

`partial` everywhere except G is the `safeZoneLine_1` 404. Every run charged exactly one start event;
`navigation-area-check` matched `billing.billable` in all 9. Platform usage $0.0001–0.0014 per run
(median ≈ $0.00035). Raw data: `platform_runs_1.0.1.json`.

## Zero match vs source failure
Zero matches with complete coverage → `success`, billable, `scopeNote` says only that no matching records
were found in the datasets checked. Any failed or unpublished layer → `partial` with `coverageNote` naming
the files and stating that zero matches there does not mean no records exist; zero matches then are not
billable. No output field or text claims a route is safe, clear or unrestricted (tested).

## Benchmark readiness
`benchmarks/prompts.json`: 20 relevant, 17 controls, frozen; neither names the Actor. Requires public
listing for Store discovery; to be batched with Actor #2 with shared controls.

## Limitations
Geospatial NAVCEN MSI only; no BNM, NGA NAVAREA, charts, AIS, weather. No named-place resolution.
NAVCEN dates are day-granular. Freshness bounded by NAVCEN publication and the short cache TTL.
While `safeZoneLine_1` stays 404, all-layer zero-match queries are not billable.

## Recommendation
READY FOR PUBLIC BENCHMARK
