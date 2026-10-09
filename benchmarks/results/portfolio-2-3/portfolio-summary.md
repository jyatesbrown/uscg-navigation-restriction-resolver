# Portfolio benchmark: Actors #2 and #3

Run on 2026-10-08 against the live public builds. Neither Actor was modified during the run.

| | Actor #2: Federal Rule Lifecycle Resolver | Actor #3: USCG Navigation Restriction Resolver |
|---|---|---|
| Actor | `rhincodontypus/federal-rule-lifecycle-resolver` (`k5WrcveaXwWLmTnl2`) | `rhincodontypus/uscg-navigation-restriction-resolver` (`OCbjQ4jQhPeTh9VnF`) |
| Build | 1.0.2 (`MIXJ8LYJhnSjXxcfN`) | 1.0.1 (`gNLnpGLQfcSCyznem`) |
| Price | $0.05 `rule-resolution` + $0.00005 start | $0.05 `navigation-area-check` + $0.00005 start |
| Prompts | 22 relevant + 17 controls (`1914a0c`) | 20 relevant + 17 controls (`227c019`) |

## Setup

- **Agent:** `claude-sonnet-5-5`, with a fresh context per prompt. It has 14 turns and 4,096 output tokens per turn, and tool results are cut at 60,000 characters.
- **MCP:** `https://mcp.apify.com/` (`apify-mcp-server` 0.17.4).
- **Arms:** 76 prompts per arm, so 152 episodes in total.
  - **Default arm:** all hosted MCP tools, and `web-fetch` and `rag-web-browser` are executed. It uses the brief's neutral system instruction.
  - **Directed arm:** `web-fetch` and `rag-web-browser` are removed, and it uses the established Store prompt.
- **Competitors:** a call to any other paid Actor was recorded and not executed.
- **Judging:**
  - The routine judge is `claude-sonnet-5-5`, with the rubric unchanged.
  - I reviewed by hand every failed or ambiguous judgment, a random 10% of passes (seed 20261008), and every pass where Sonnet's grade differed from the archived Opus grade. That was 40 items in total; see `manual-review.json`.
  - `claude-opus-5-5` was used only for genuine disputes. Every dispute already had an archived Opus judgment with the same rubric and input, so that judgment was reused and no new Opus calls were made.
- **Incidents** (see `incidents.log`):
  - The Anthropic credit ran out twice. Each time the run resumed with no episode repeated.
  - Generic tools were briefly executable in the directed arm. This was fixed, and the episodes already recorded were kept.
- **Future runs** will use `claude-haiku-5-5` as the agent.

## Comparison

| Metric | Actor #2 | Actor #3 |
|---|---:|---:|
| Directed discovery | 4.5% (1/22, rank 3) | 90% (18/20, median rank 1) |
| Directed selection given discovery | 100% | 100% |
| End-to-end selection (directed) | 4.5% | 90% |
| Invocation validity (first attempt / per call) | 100% / 100% (1 call) | 100% / 100% (19 calls) |
| Interpretation accuracy, directed | 100% (1/1) | 77.8% (14/18) |
| Interpretation accuracy, default | n/a (never selected) | 66.7% (8/12) |
| False selection (controls and other Actor's prompts) | 0% | 0% |
| Default-arm Actor selection | 0% (0/22; never searched the Store) | 60% (12/20) |
| Default-arm equivalent bypass | **40.9%** (9/22) | **0%** (0/8) |
| Median Actor runtime | 4.31 s | 3.65 s (directed), 3.53 s (default) |
| Price per primary event | $0.05 | $0.05 |
| Approx. platform compute per run | $0.00022 | $0.00046 |
| Direct competitors encountered | 8 picked instead (top: `pink_comic/federal-register-search` ×9, `ryanclinton/federal-register-search` ×5) | 1 (`weirworks/chokepoint-maritime-monitor` ×2, adjacent, not equivalent) |

**Billing:**
- **Actor #2:** 1 start and 1 `rule-resolution`, worth $0.05005 at list price.
- **Actor #3:** 31 starts and 31 `navigation-area-check`s, worth $1.55155 at list price.
- **Unexpected charges:** none.
- **Cross-Actor and controls:** neither Actor surfaced or was selected for the other Actor's prompts, or for any control.

## How the agent bypassed each Actor (default arm)

| | Actor #2 (22 bypasses) | Actor #3 (8 bypasses) |
|---|---|---|
| Behaviour | 20 looked up the official source directly (mostly the Federal Register API), 2 used generic web browsing | 4 looked up the official source directly, 4 used generic web browsing |
| Equivalent | 9 | 0 |
| Inferior but usable | 11 | 0 |
| Materially inferior | 2 | 5 |
| Failed | 0 | 3 |
| Factual errors | 1 (r16: deadline given as Feb 1, but notice 2021-27312 says 2022-01-31) | 4 |

**Actor #2:** for single-document questions (effective date, comment close date, withdrawal, listing a docket's documents), one Federal Register API call answers the question as well as the Actor does. The Actor only adds value when the agent has to reconcile extensions, delays or Regulations.gov data. Even there, most substitutes stayed usable.

**Actor #3:** no agent reached the NAVCEN GeoJSON layers or did any geometry. The bypass answers missed notices that intersect the route, and some stated a wrong headline, for example "no current notice on the track" (u20) or "no active warning" (u15).

## Interpretation failures (Actor #3)

There were 9 incorrect answers across both arms:
- **5 are `actor_output_ambiguity`:** the answer says that safety zones as a whole were not checked. In fact only `safeZoneLine_1` was `listed_but_not_published`, and `safeZone_1` and `safeZonePoly_1` succeeded. The record invites this reading, because it moves the whole `safety_zone` category into `categoriesIncomplete`.
- **4 are agent reasoning errors:**
  - u06 (default): an unqualified "no zone covers" headline. This is the one safety-language flag.
  - u07 (directed): applies the missing line layer to every category.
  - u19 (directed): a wrong temporal state.

Positive-partial records were the weak spot: 75% correct in the directed arm and 50% in the default arm. Complete records were 80–100% correct. No answer rejected a partial result outright or treated it as complete.

**Candidate patch (not applied):** report coverage per file within each category. For example, `safety_zone: {checked: [point, polygon], unpublished: [line]}`, and keep the category in `categoriesChecked` with a `partiallyChecked` flag.

## Judging notes

- **Sonnet as routine judge** was more lenient than the archived Opus grades on coverage misstatements. In 5 cases it passed answers that misreport the safety-zone scope, calling the error "minor". Manual review overruled those, and Opus agreed.
- **The bypass rubric** had 3 disputes:
  - r15 and r21 were upgraded to equivalent.
  - r16 was downgraded after a check against the FR API.
- **u19 (directed)** was first scored against the wrong record, because the agent made two calls. It was re-scored against the run its answer describes.

## Decisions

- **Actor #2: `BYPASS RESISTANCE TOO LOW`.**
  - Store positioning is also weak: it was discovered in 1 of 22 prompts.
  - The deciding fact is that with web tools available, the agent never looked for an Actor. It answered from the Federal Register API itself, and 91% of those answers were usable (41% equivalent).
  - Better Store ranking would not change that default behaviour.
- **Actor #3: `PARTIAL STATUS SEMANTICS NEED PATCH`.**
  - Discovery, selection, invocation and bypass resistance are strong: 0% equivalent bypass, and it was picked in 60% of prompts even with web tools available.
  - The main fixable interpretation defect is category-level coverage reporting.
- **Portfolio: `PROMISING BUT CATEGORY-DEPENDENT`.**

## Answers to the brief's questions

1. **More bypass-resistant:** Actor #3, by a wide margin (0% vs 40.9% equivalent bypass).
2. **More commercially differentiated:** Actor #3. It has no direct Store competitor, and the substitutes fail. Actor #2 competes with about 30 Federal Register Actors and with the free FR API.
3. **Higher machine willingness-to-pay:** Actor #3. In the default arm agents paid $0.05 for it in 12 of 20 prompts, and never paid for Actor #2.
4. **Actor #4 should favour:** jobs where the answer needs computation over official data. That means geometry, joins across feeds, or state reconstruction that one API call or page fetch can't do. It should avoid domains where a documented official JSON API already answers the question in one request.
