# USCG Navigation Restriction Resolver

Check a point, a vessel route or a bounding box against **current official U.S. Coast Guard maritime safety
information**. Returns one structured record listing the intersecting safety zones, hazards to navigation,
marine construction, marine events, naval activity, space-operation areas, temporary aids-to-navigation
changes, TESS advisories and geospatial MSIBs, with official text, validity windows, geometry and source
provenance.

> **Not navigational advice.** This Actor reports official notice records. It never says a route is safe,
> clear or unrestricted. Zero matches means no matching records were found in the official datasets
> successfully checked. It is not a statement that navigation is hazard-free or unrestricted. Mariners must
> still consult official charts, current Local and Broadcast Notices to Mariners, VHF broadcasts and
> applicable Coast Guard instructions, and follow onboard navigation and safety procedures.

## What it does

Point / route / bbox → official USCG NAVCEN Maritime Safety Information layers → spatially relevant notices.

- **Source:** the GeoJSON layers published by the USCG Navigation Center (NAVCEN) at
  [navcen.uscg.gov/msi](https://www.navcen.uscg.gov/msi). No third-party data.
- **Geometry:** buffers and intersections are computed in a local azimuthal-equidistant projection centred on
  your query, so nautical-mile radii and corridors are real distances (not degree buffers). Reported distances
  are geodesic on the WGS84 ellipsoid.
- **Time:** each notice is classified `active`, `upcoming` or `unknown` (no dates published) at `atTime`
  (default: now). Expired notices are excluded and counted.
- **Coverage:** every dataset file checked is listed with its status (`success`, `unavailable`, `timeout`,
  `invalid_format`, `listed_but_not_published`) and publication time. A failed layer makes the result
  `partial`; it never looks like zero notices.
- **Listed but not published:** if NAVCEN's file index lists a file that NAVCEN does not serve (HTTP 404),
  it is reported in `coverage.unpublishedDatasets`. It is not treated as checked or empty, so coverage is
  incomplete and `coverage.coverageNote` says records there were not checked.
- **Per-file category coverage:** `coverage.categories` gives each requested category a `status`
  (`complete`, `partial`, `unavailable`) and lists its dataset files as `checked`, `unavailable` or
  `listedButNotPublished`. A category with any file checked stays in `categoriesChecked`; if some of its files
  were not checked it is also in `categoriesPartiallyChecked`. Example: today NAVCEN lists `safeZoneLine_1`
  but does not serve it, so `safety_zone` is `partial` with `safeZone_1` and `safeZonePoly_1` checked.

## Input

Provide exactly one of `point`, `route` or `bbox` (WGS84 decimal degrees).

```json
{"point": {"lat": 40.89, "lon": -73.78}, "radiusNm": 5}
```

```json
{"route": [{"lat": 29.31, "lon": -94.70}, {"lat": 29.73, "lon": -95.03}], "corridorNm": 1}
```

```json
{"bbox": {"south": 40.4, "west": -74.3, "north": 40.9, "east": -73.7}}
```

| Field | Notes |
|---|---|
| `point` + `radiusNm` | Default 5 nm, 0.1–50 nm. |
| `route` + `corridorNm` | 2–200 ordered positions you supply (≤1500 nm). Corridor half-width default 1 nm, 0.1–25 nm. The Actor does not plan routes. |
| `bbox` | ≤10° per side; must not cross the antimeridian. |
| `atTime` | ISO 8601 with timezone. Default now (UTC). |
| `categories` | Optional subset of `safety_zone`, `hazard_to_navigation`, `marine_construction`, `marine_event`, `naval_activity`, `space_operation`, `temporary_change`, `tess_advisory`, `msib`. |

Named places (e.g. "Port Canaveral") are not resolved in v1; pass coordinates.

## Output (one dataset item)

| Field | Meaning |
|---|---|
| `status` | `success` (all requested layers checked), `partial` (some layers failed), `source_unavailable`, `invalid_input`. |
| `coverage` | `categories` (per-category status and files), `categoriesChecked`, `categoriesPartiallyChecked`, `categoriesUnavailable`, `categoriesFailed`, `categoriesIncomplete`, `completeForRequestedLayers`, `coverageNote`, `sourceFailures`, `unpublishedDatasets`, per-file `datasets`, `notCovered`. |
| `summary` | `matchedNoticeCount`, `activeCount`, `upcomingCount`, `unknownValidityCount`, `expiredExcludedCount`, `categoriesMatched`, `byCategory`. |
| `notices[]` | `category`, `title`, `validity`, `effectiveWindow`, official GeoJSON `geometry`, `relationshipToQuery` (`intersectsQueryGeometry`, `withinSearchArea`, `minimumDistanceNm`, `routePosition`), verbatim `officialText`, `source` (dataset URL, record dates). |
| `scopeNote` | What a zero-match result does and does not mean. |

Route results are ordered by `routePosition` (approximate fraction of your route length where the notice is
nearest or first intersected); point and bbox results by distance. No severity score is invented: use the
official category and wording.

## Ideal use cases

Pre-voyage information gathering, maritime operations workflows, route screening, harbor/port
reconnaissance, marine construction planning, space-operation awareness, and autonomous agent research.

## What it does NOT do

Route planning, collision avoidance, chart replacement, navigational clearance, weather routing, legal
compliance determination, or assurance of safe transit. It does not check Broadcast Notices to Mariners
(planned), NOAA charts, NGA NAVAREA warnings, AIS, tides or weather.

## Pricing

Pay per event: `navigation-area-check` **$0.05** per query, plus a $0.00005 start event.

- Charged when all requested layers were checked, **including zero matches**.
- Charged when some layers failed but matching notices were still found (status `partial`).
- **Not charged** for invalid input, or when coverage is incomplete (failed or unpublished layers) and nothing was found.

## Limitations

- Coverage is limited to what NAVCEN publishes as geospatial MSI records; notices without geometry are not
  returned. NAVCEN publishes dates at day granularity.
- Freshness depends on NAVCEN's publication. Layers are reused for at most a short period, and only while
  NAVCEN's file index shows the same publication time.
- Broadcast Notices to Mariners are not included in v1.
