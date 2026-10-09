"""Score the portfolio benchmark (Actors #2 and #3) from raw harness episodes.

Usage:
    APIFY_TOKEN=... ANTHROPIC_API_KEY=... python benchmarks/portfolio-2-3/analyze_portfolio.py --judge-model <id>
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
from pathlib import Path

import httpx

HERE = Path(__file__).parent
RES = HERE.parent / "results" / "portfolio-2-3"
API = "https://api.apify.com/v2"
NAMES = {
    "actor2": "rhincodontypus/federal-rule-lifecycle-resolver",
    "actor3": "rhincodontypus/uscg-navigation-restriction-resolver",
}
IDS = {"k5WrcveaXwWLmTnl2": "actor2", "OCbjQ4jQhPeTh9VnF": "actor3"}
BY_NAME = {v: k for k, v in NAMES.items()}
PRIMARY_EVENT = {"actor2": "rule-resolution", "actor3": "navigation-area-check"}
PRICE = {"apify-actor-start": 0.00005, "rule-resolution": 0.05, "navigation-area-check": 0.05}
CAPABILITY = {
    "actor2": "Resolves one U.S. federal rulemaking (from RIN, docket ID, FR document number/URL or rule name) "
    "across the Federal Register and Regulations.gov APIs into one structured lifecycle record: related "
    "documents, RIN/docket relationships, proposed vs final stage, original and extended/reopened comment "
    "deadlines, original vs current (delayed) effective dates, withdrawal, provenance, confidence, and "
    "explicit limitations (no court/litigation status).",
    "actor3": "Intersects a point+radius, route+corridor, or bounding box with every current official USCG "
    "NAVCEN maritime safety information GeoJSON layer (safety zones, hazards to navigation, marine "
    "construction, marine events, naval activity, space operations, temporary changes, TESS, MSIB) using "
    "metric geodesic geometry; returns each intersecting notice with category, active/upcoming/expired/"
    "unknown validity, distance/route position, official text, provenance, and per-layer coverage "
    "(including layers NAVCEN lists but does not publish). Never states a route is safe or clear.",
}

RUBRIC = {
    "actor2": """You grade whether an assistant's answer correctly interprets a dataset record returned by a
federal rule lifecycle resolver. Judge ONLY against the record (do not use outside knowledge to mark the answer
wrong unless the record supports it). Check, where relevant to the question:
proposed vs final rule; comment-period status; original vs extended/reopened comment deadline; final-rule
publication date; original vs current effective date; delays/extensions; RIN/docket relationships; source
provenance; resolution status/confidence (resolved/partial/ambiguous/not_found...); limitations (the record does
not cover court/litigation status). Flag enforceabilityOverclaim=true if the answer turns the administrative
lifecycle into an unsupported claim about current legal enforceability (e.g. "this rule is legally in force and
must be complied with" or "it was struck down") that the record does not state.
If the answer is incorrect, set failureClass to exactly one of: actor_output_ambiguity, agent_reasoning_error,
source_data_limitation, parser_data_defect, store_positioning_problem, judge_rubric_issue.
Return only JSON: {"correct": true|false, "failureClass": null|"...", "errors": ["short labels"],
"enforceabilityOverclaim": true|false, "notes": "one or two sentences"}.""",
    "actor3": """You grade whether an assistant's answer correctly interprets a dataset record returned by a
USCG NAVCEN maritime-safety-information spatial resolver. Judge ONLY against the record. Check, where relevant:
point/route/corridor relationship (inside, within distance, crossing); notice category; active/upcoming/expired/
unknown temporal state; route position if present; official provenance; coverage completeness, including any
dataset with state listed_but_not_published and status partial vs success. An answer is wrong if it states a
route/area is safe, clear, unrestricted, hazard-free or approved, or turns zero matching records into absence of
hazards; set safetyLanguage=true in that case.
For a record whose coverage is incomplete (status partial), fill partialHandling: usesMatches (correctly uses
the available matches; null if there are none), statesMissingCoverage (mentions the incomplete/unpublished
layer or that coverage is incomplete), rejectsWhole (wrongly dismisses the whole result as unusable),
assumesComplete (treats coverage as complete). Otherwise partialHandling is null.
If incorrect, set failureClass to exactly one of: actor_output_ambiguity, agent_reasoning_error,
source_data_limitation, parser_data_defect, store_positioning_problem, judge_rubric_issue.
Return only JSON: {"correct": true|false, "failureClass": null|"...", "errors": ["short labels"],
"safetyLanguage": true|false, "partialHandling": null|{"usesMatches": true|false|null,
"statesMissingCoverage": true|false, "rejectsWhole": true|false, "assumesComplete": true|false},
"notes": "one or two sentences"}.""",
}

BYPASS_RUBRIC = """An AI agent answered a user request WITHOUT using a specialised tool. Classify what it did and
how good the substitute was compared with the specialised tool's capability (described below). If a reference
record from the specialised tool is supplied, use it to judge whether the agent's answer is accurate/complete.
behavior: exactly one of generic_web_browsing, direct_official_source_lookup, manual_multi_source_reconstruction,
manual_geospatial_reasoning, different_actor, answer_from_model_memory, cannot_complete, other.
(direct_official_source_lookup = fetched an official site/API page directly, e.g. federalregister.gov,
regulations.gov, navcen.uscg.gov; manual_multi_source_reconstruction = combined several official documents itself;
manual_geospatial_reasoning = compared coordinates/geometry itself.)
substitute: exactly one of
- equivalent: realistically the same quality/structure/reliability with little extra effort;
- inferior_but_usable: answers the immediate question but loses meaningful structure, provenance, reconciliation
  or certainty;
- materially_inferior: cannot reasonably reproduce the capability without substantial extra tooling/multi-step work
  (including a confident but incomplete/unverified answer);
- failed: no useful answer.
Also set factualErrors=true if the answer contains a statement contradicted by the reference record or the fetched
official pages, and safetyLanguage=true if it declares a route/area safe/clear/unrestricted/hazard-free.
Return only JSON: {"behavior": "...", "substitute": "...", "factualErrors": true|false, "safetyLanguage":
true|false, "notes": "one or two sentences"}."""


def apify(path: str):
    r = httpx.get(f"{API}{path}", headers={"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def llm_json(model: str, content: str) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ["BENCHMARK_LLM_API_KEY"]
    for attempt in range(3):
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            timeout=300,
            json={"model": model, "max_tokens": 2000, "messages": [{"role": "user", "content": content}]},
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        if r.status_code in (429, 500, 529) and attempt < 2:
            continue
        r.raise_for_status()
        text = "".join(b["text"] for b in r.json()["content"] if b["type"] == "text")
        return json.loads(text[text.index("{") : text.rindex("}") + 1])
    raise RuntimeError("judge failed")


def key_of(target: str | None) -> str | None:
    if not target:
        return None
    base = target.split(":")[0]
    return BY_NAME.get(base) or IDS.get(base)


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def stats(xs: list[float]) -> dict | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {
        "n": len(xs),
        "mean": round(statistics.mean(xs), 2),
        "median": round(statistics.median(xs), 2),
        "min": round(min(xs), 2),
        "max": round(max(xs), 2),
    }


def clip(obj, n: int) -> str:
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "...[truncated]"


def load(arm: str) -> list[dict]:
    p = RES / f"raw-{arm}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def invocation_rows(e: dict, cache: dict) -> list[dict]:
    rows = []
    for c in e["actorCalls"]:
        k = key_of(c["actor"])
        if not k:
            continue
        sc = c.get("structured") or {}
        run_id = sc.get("runId")
        if run_id and run_id not in cache:
            run = apify(f"/actor-runs/{run_id}")["data"]
            ds = run.get("defaultDatasetId")
            items = apify(f"/datasets/{ds}/items?clean=1") if ds else []
            cache[run_id] = {"run": run, "record": items[0] if isinstance(items, list) and items else None}
        got = cache.get(run_id) or {"run": {}, "record": None}
        run, rec = got["run"], got["record"]
        status = (rec or {}).get("status")
        rows.append(
            {
                "actor": k,
                "runId": run_id,
                "input": c.get("input"),
                "isError": c.get("isError"),
                "callError": None if run_id else (c.get("resultText") or "")[:400],
                "runStatus": run.get("status"),
                "datasetStatus": status,
                "executionSuccess": run.get("status") == "SUCCEEDED" and rec is not None,
                "valid": run.get("status") == "SUCCEEDED" and rec is not None and status != "invalid_input",
                "runTimeSecs": (run.get("stats") or {}).get("runTimeSecs"),
                "toolLatencyS": c.get("latencyS"),
                "chargedEventCounts": run.get("chargedEventCounts"),
                "billable": ((rec or {}).get("billing") or {}).get("billable"),
                "record": rec,
            }
        )
    return rows


def partial_class(rec: dict) -> str | None:
    if not rec or rec.get("status") not in ("success", "partial"):
        return None
    n = len(rec.get("notices") or [])
    if rec["status"] == "partial":
        return "positive_partial" if n else "zero_match_partial"
    return "complete_positive" if n else "complete_zero_match"


def trace_summary(e: dict) -> str:
    out = []
    for t in e["toolTrace"]:
        out.append(f"- {t['tool']} {clip(t['args'], 400)} -> {(t.get('resultText') or '(not executed)')[:1500]}")
    return "\n".join(out) or "(no tool calls)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge-model", default="claude-sonnet-5-5")
    a = ap.parse_args()
    jpath = RES / f"judgments-{a.judge_model}.json"
    judg = json.loads(jpath.read_text()) if jpath.exists() else {}
    cpath = RES / ".run-cache.json"
    cache = json.loads(cpath.read_text()) if cpath.exists() else {}
    arms = {arm: load(arm) for arm in ("default", "directed")}
    reference = {}
    episodes = {}
    for arm, eps in arms.items():
        for e in eps:
            e["_inv"] = invocation_rows(e, cache)
            for r in e["_inv"]:
                if r["record"] and r["actor"] == e["group"] and r["valid"]:
                    reference.setdefault(e["id"], r["record"])
            episodes[(arm, e["id"])] = e
    cpath.write_text(json.dumps(cache))

    rpath = RES / "manual-review.json"
    reviewed = json.loads(rpath.read_text())["items"] if rpath.exists() else {}

    def judged(key: str, content_fn):
        if key not in judg:
            judg[key] = {**llm_json(a.judge_model, content_fn()), "judgeModel": a.judge_model}
            jpath.write_text(json.dumps(judg, indent=1, ensure_ascii=False))
        final = ((reviewed.get(key) or {}).get("review") or {}).get("final")
        return {**judg[key], **final, "overriddenBy": "manual_review"} if final else judg[key]

    summary = {"arms": {}, "crossSelection": {}, "billing": {}, "competitors": {}}
    for arm, eps in arms.items():
        arm_out = {}
        for actor in ("actor2", "actor3"):
            rel = [e for e in eps if e["group"] == actor]
            non = [e for e in eps if e["group"] != actor]
            rows = []
            for e in rel:
                ranks = [s["oursRank"][actor] for s in e["searches"] if s["oursRank"].get(actor)]
                inv = [r for r in e["_inv"] if r["actor"] == actor]
                row = {
                    "id": e["id"],
                    "class": e["category"],
                    "rank": min(ranks) if ranks else None,
                    "searched": bool(e["searches"]),
                    "selected": bool(inv) or actor in e.get("portfolioCalls", []),
                    "firstSelection": e["selected"],
                    "invocations": [{k: v for k, v in r.items() if k != "record"} for r in inv],
                    "elapsedS": e.get("elapsedS"),
                    "finalAnswer": e.get("finalAnswer"),
                    "stoppedAt": e.get("stoppedAt"),
                }
                last = next((r for r in reversed(inv) if r["record"]), None)
                if last:
                    rec = last["record"]
                    row["recordStatus"] = rec.get("status")
                    if actor == "actor3":
                        row["partialClass"] = partial_class(rec)
                    row["interpretation"] = judged(
                        f"interp|{arm}|{e['id']}",
                        lambda e=e, rec=rec, actor=actor: (
                            f"{RUBRIC[actor]}\n\nUSER QUESTION:\n{e['prompt']}\n\nDATASET RECORD:\n"
                            f"{clip(rec, 150000)}\n\nASSISTANT ANSWER:\n{e.get('finalAnswer') or ''}"
                        ),
                    )
                if arm == "default" and not row["selected"]:
                    ref = reference.get(e["id"])
                    row["bypass"] = judged(
                        f"bypass|{arm}|{e['id']}",
                        lambda e=e, ref=ref, actor=actor: (
                            f"{BYPASS_RUBRIC}\n\nSPECIALISED TOOL CAPABILITY:\n{CAPABILITY[actor]}\n\n"
                            f"USER REQUEST:\n{e['prompt']}\n\nAGENT TOOL TRACE:\n{trace_summary(e)}\n\n"
                            f"REFERENCE RECORD FROM SPECIALISED TOOL (same request, other benchmark arm):\n"
                            f"{clip(ref, 60000) if ref else '(none available)'}\n\n"
                            f"AGENT FINAL ANSWER:\n{e.get('finalAnswer') or ''}"
                        ),
                    )
                rows.append(row)
            disc = [r for r in rows if r["rank"]]
            sel = [r for r in rows if r["selected"]]
            invs = [i for r in rows for i in r["invocations"]]
            interp = [r for r in rows if r.get("interpretation")]
            byp = [r for r in rows if r.get("bypass")]
            ranks = [r["rank"] for r in disc]
            m = {
                "relevant": len(rows),
                "discovery": {
                    "surfaced": len(disc),
                    "rate": pct(len(disc), len(rows)),
                    "top1": pct(sum(x <= 1 for x in ranks), len(rows)),
                    "top3": pct(sum(x <= 3 for x in ranks), len(rows)),
                    "top5": pct(sum(x <= 5 for x in ranks), len(rows)),
                    "meanRank": round(statistics.mean(ranks), 2) if ranks else None,
                    "medianRank": statistics.median(ranks) if ranks else None,
                    "searchedAtAll": sum(r["searched"] for r in rows),
                },
                "selection": {
                    "selected": len(sel),
                    "givenDiscovery": pct(sum(r["selected"] for r in disc), len(disc)),
                    "endToEnd": pct(len(sel), len(rows)),
                },
                "invocation": {
                    "calls": len(invs),
                    "firstAttemptValid": pct(
                        sum(r["invocations"][0]["valid"] for r in sel if r["invocations"]), len(sel)
                    ),
                    "eventualValid": pct(sum(any(i["valid"] for i in r["invocations"]) for r in sel), len(sel)),
                    "perCallValid": pct(sum(i["valid"] for i in invs), len(invs)),
                    "executionSuccess": pct(sum(i["executionSuccess"] for i in invs), len(invs)),
                },
                "interpretation": {
                    "graded": len(interp),
                    "correct": sum(r["interpretation"]["correct"] for r in interp),
                    "accuracy": pct(sum(r["interpretation"]["correct"] for r in interp), len(interp)),
                    "failureClasses": dict(
                        collections.Counter(
                            r["interpretation"].get("failureClass")
                            for r in interp
                            if not r["interpretation"]["correct"]
                        )
                    ),
                    "enforceabilityOverclaims": sum(
                        bool(r["interpretation"].get("enforceabilityOverclaim")) for r in interp
                    ),
                    "safetyLanguage": sum(bool(r["interpretation"].get("safetyLanguage")) for r in interp),
                },
                "abstention": {
                    "nonRelevantPrompts": len(non),
                    "falseDiscovery": sum(any(s["oursRank"].get(actor) for s in e["searches"]) for e in non),
                    "falseSelection": sum(actor in e.get("portfolioCalls", []) for e in non),
                    "falseInvocation": sum(any(r["actor"] == actor and r["runId"] for r in e["_inv"]) for e in non),
                    "falseSelectionRate": pct(sum(actor in e.get("portfolioCalls", []) for e in non), len(non)),
                },
                "latency": {
                    "actorRunTimeSecs": stats([i["runTimeSecs"] for i in invs]),
                    "toolRoundTripS": stats([i["toolLatencyS"] for i in invs]),
                    "episodeS": stats([r["elapsedS"] for r in rows]),
                },
                "firstSelections": dict(collections.Counter(r["firstSelection"] for r in rows)),
            }
            if arm == "default":
                nb = len(byp)
                m["bypass"] = {
                    "bypassed": nb,
                    "bypassRate": pct(nb, len(rows)),
                    "behavior": dict(collections.Counter(r["bypass"]["behavior"] for r in byp)),
                    "substitute": dict(collections.Counter(r["bypass"]["substitute"] for r in byp)),
                    "equivalentBypass": sum(r["bypass"]["substitute"] == "equivalent" for r in byp),
                    "equivalentBypassRate": pct(sum(r["bypass"]["substitute"] == "equivalent" for r in byp), len(rows)),
                    "factualErrors": sum(bool(r["bypass"].get("factualErrors")) for r in byp),
                    "safetyLanguage": sum(bool(r["bypass"].get("safetyLanguage")) for r in byp),
                }
            if actor == "actor3":
                pc = collections.defaultdict(lambda: [0, 0])
                for r in interp:
                    c = r.get("partialClass") or "other"
                    pc[c][0] += 1
                    pc[c][1] += r["interpretation"]["correct"]
                ph = [
                    r["interpretation"].get("partialHandling")
                    for r in interp
                    if r["interpretation"].get("partialHandling")
                ]
                m["partialAnalysis"] = {
                    "byClass": {
                        k: {"graded": v[0], "correct": v[1], "accuracy": pct(v[1], v[0])} for k, v in pc.items()
                    },
                    "partialHandling": {
                        f: sum(bool(h.get(f)) for h in ph)
                        for f in ("usesMatches", "statesMissingCoverage", "rejectsWhole", "assumesComplete")
                    },
                    "partialGraded": len(ph),
                }
            comp = collections.Counter()
            ahead = collections.Counter()
            best = {}
            for e in rel:
                for s in e["searches"]:
                    ours = s["oursRank"].get(actor)
                    for i, n in enumerate(s["ranking"]):
                        if n in BY_NAME:
                            continue
                        comp[n] += 1
                        best[n] = min(best.get(n, 99), i + 1)
                        if ours is None or i + 1 < ours:
                            ahead[n] += 1
            chosen = collections.Counter(
                r["firstSelection"]
                for r in rows
                if r["firstSelection"]
                and not key_of(r["firstSelection"])
                and r["firstSelection"] not in ("apify/web-fetch", "apify/rag-web-browser")
            )
            m["competitors"] = {
                "appearances": dict(comp.most_common(15)),
                "bestRank": {n: best[n] for n, _ in comp.most_common(15)},
                "outrankedOursOrOursAbsent": dict(ahead.most_common(15)),
                "selectedInsteadOfOurs": dict(chosen),
            }
            arm_out[actor] = {"metrics": m, "rows": rows}
        controls = [e for e in eps if e["group"] == "control"]
        arm_out["controls"] = {
            "n": len(controls),
            "surfacedOurs": {k: sum(any(s["oursRank"].get(k) for s in e["searches"]) for e in controls) for k in NAMES},
            "selectedOurs": {k: sum(k in e.get("portfolioCalls", []) for e in controls) for k in NAMES},
            "firstSelections": dict(collections.Counter(e["selected"] for e in controls)),
            "rows": [
                {
                    "id": e["id"],
                    "class": e["category"],
                    "selected": e["selected"],
                    "portfolioCalls": e.get("portfolioCalls"),
                    "surfaced": {k: [s["oursRank"].get(k) for s in e["searches"]] for k in NAMES},
                }
                for e in controls
            ],
        }
        a2_on_3 = [e for e in eps if e["group"] == "actor3"]
        a3_on_2 = [e for e in eps if e["group"] == "actor2"]
        summary["crossSelection"][arm] = {
            "actor2SurfacedForActor3Prompts": sum(
                any(s["oursRank"].get("actor2") for s in e["searches"]) for e in a2_on_3
            ),
            "actor3SurfacedForActor2Prompts": sum(
                any(s["oursRank"].get("actor3") for s in e["searches"]) for e in a3_on_2
            ),
            "actor2SelectedForActor3Prompts": sum("actor2" in e.get("portfolioCalls", []) for e in a2_on_3),
            "actor3SelectedForActor2Prompts": sum("actor3" in e.get("portfolioCalls", []) for e in a3_on_2),
            "eitherSelectedOnControls": sum(bool(e.get("portfolioCalls")) for e in controls),
        }
        summary["arms"][arm] = arm_out
    for actor in NAMES:
        runs = [v["run"] for v in cache.values() if key_of(v["run"].get("actId")) == actor]
        ev = collections.Counter()
        for r in runs:
            ev.update(r.get("chargedEventCounts") or {})
        unexpected = [
            r["id"]
            for r in runs
            if (r.get("chargedEventCounts") or {}).get("apify-actor-start", 0) != 1
            or (r.get("chargedEventCounts") or {}).get(PRIMARY_EVENT[actor], 0)
            != int(bool(((cache.get(r["id"]) or {}).get("record") or {}).get("billing", {}).get("billable")))
        ]
        summary["billing"][actor] = {
            "actorStarts": len(runs),
            "eventCounts": dict(ev),
            "nominalValueUsd": round(sum(PRICE.get(k, 0) * v for k, v in ev.items()), 5),
            "platformUsageUsd": round(sum(r.get("usageTotalUsd") or 0 for r in runs), 5),
            "unexpectedChargeRuns": unexpected,
        }
    (RES / "portfolio-summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    for arm, eps in arms.items():
        for grp, fname in (("actor2", "actor2"), ("actor3", "actor3"), ("control", "controls")):
            with (RES / f"{fname}-{arm}.jsonl").open("w") as f:
                for e in eps:
                    if e["group"] == grp:
                        f.write(json.dumps({k: v for k, v in e.items() if k != "_inv"}, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                arm: {
                    k: v["metrics"] if "metrics" in v else {kk: vv for kk, vv in v.items() if kk != "rows"}
                    for k, v in d.items()
                }
                for arm, d in summary["arms"].items()
            },
            indent=1,
            default=str,
        )[:20000]
    )
    print(json.dumps({"cross": summary["crossSelection"], "billing": summary["billing"]}, indent=1))


if __name__ == "__main__":
    main()
