# Actor #3 coverage patch (build 1.1.1): reduced verification benchmark

**Decision: PATCH VALIDATED — ACTOR #3 MAINTENANCE MODE**

- Agent: `claude-haiku-5-5`, directed (Store) arm, fresh context per prompt.
- Judge: `claude-sonnet-5-5`, same rubric as `portfolio-2-3`. Manual review of every failure plus a 10% pass sample (seed 20261009). No Opus calls.
- Prompts: 10 relevant (u01 u05 u06 u07 u13 u16 u18 u19 + new zero-match z01 z02), 5 controls (k01 k04 k11 k15 k16).

| Metric | Result |
|---|---|
| Discovery | 8/10 (all rank 1) |
| Selection given discovery | 8/8 |
| Invocation validity | 9/9 calls valid, 100% executed |
| Interpretation (after manual review) | 5/8 |
| Partial-result interpretation | 3/5 (zero-match partial 2/2, positive partial 1/3) |
| Coverage misstatements ("safety zones not checked") | **0/8** (previous benchmark: 5 of 9 interpretation failures) |
| False selection on controls | 0/5 |
| Billing | 9 runs: 9 start events; 7 `navigation-area-check` charges, exactly the 7 records with `billable: true` (both partial zero-match runs uncharged) |

## Coverage ambiguity

Every partial record was described as partial. No answer said safety zones were unchecked or treated the result as complete. The decisive case is u06 (safety-zone-only, zero matches): the answer says the point and polygon safety-zone datasets were checked with no matches and that `safeZoneLine_1` was listed but unpublished, so a line-defined zone could be missed.

## Remaining failures (not coverage)

- u01: miscounted route-intersecting notices (5 vs 6), swapped two distances, misread the regatta day.
- u18: said a notice 0.082 nm away "intersects your point".
- u19: mis-itemised safety zones and the answer stops after one section. The analyzer had graded it against the agent's second call; it was re-judged against the record the answer describes, and still fails for reasoning, not coverage.
- u07 / z01 not selected: NOTAM misreading, and search terms that did not surface the Actor. These are unrelated to the patch.

Details: `manual-review.json`, `judgments-claude-sonnet-5-5.json`, `rejudge-u19-first-record.json`, `run-metadata.json`, `live-platform-1.1.1.json`.
