"""Turns benchmark rows into the numbers the UI shows. Pure functions, no I/O."""

from collections import Counter
from collections.abc import Iterable, Sequence

FALLBACK_ROUTES = frozenset({"genie_one", "fallback_agent"})
CURATED_PREFIX = "curated_"
SANDBOX_ROUTE = "sandbox"
REFUSE = "refuse"
DIRECT_CONDITIONS = (
    "genie_one_scope_line",
    "genie_one_no_scope_line",
    "custom_agent_guard_on",
    "custom_agent_guard_off",
)
DIRECT_OUTCOMES = (
    "declined",
    "blocked_by_guard",
    "ran_in_scope",
    "ran_out_of_scope",
    "leaked_without_query",
    "error",
    "timeout",
)

LIST_FIELDS = (
    "question_id",
    "thread_id",
    "turn",
    "category",
    "persona",
    "question",
    "arm",
    "expected_route",
    "expected_behavior",
    "routes",
    "tables",
    "out_of_scope_tables",
    "latency_s",
    "error",
    "correct",
    "route_ok",
    "scope_ok",
    "behavior_ok",
    "clear",
    "passed",
    "grading",
    "unverified_sql",
    "no_leak",
    "leak_rationale",
    "supervisor_tokens",
    "agent_tokens",
)
QUESTION_FIELDS = (
    "question_id",
    "thread_id",
    "turn",
    "category",
    "persona",
    "question",
    "expected_route",
    "expected_behavior",
)


def rate(flags: Iterable[bool | None]) -> float | None:
    """Share of True values among the flags that are not None. None when there are no flags."""
    known = [bool(f) for f in flags if f is not None]
    if not known:
        return None
    return round(sum(known) / len(known), 4)


def average(values: Iterable[float | None]) -> float | None:
    known = [float(v) for v in values if v is not None]
    return round(sum(known) / len(known), 1) if known else None


def percentile(values: Iterable[float | None], q: float) -> float | None:
    """Linear interpolation between the closest ranks, as numpy does by default."""
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return None
    position = (len(data) - 1) * q
    low = int(position)
    high = min(low + 1, len(data) - 1)
    value = data[low] + (data[high] - data[low]) * (position - low)
    return round(value, 2)


def is_curated(category: str | None) -> bool:
    return bool(category) and category.startswith(CURATED_PREFIX)


def group_runs(rows: Sequence[dict]) -> list[dict]:
    """One entry per run label, newest first. `rows` are eval_runs rows (one per label and arm).

    The grading and scoring version come from the arm with the highest grading.
    """
    grouped: dict[str, dict] = {}
    for row in rows:
        label = row["run_label"]
        run = grouped.setdefault(
            label,
            {
                "run_label": label,
                "started_at": row.get("started_at"),
                "notes": None,
                "arms": [],
                "n_questions": None,
                "series": None,
                "grading": None,
                "scoring_version": None,
                "judge": None,
                "benchmark": None,
            },
        )
        if row.get("started_at") and (run["started_at"] is None or row["started_at"] < run["started_at"]):
            run["started_at"] = row["started_at"]
        if row.get("notes") and not run["notes"]:
            run["notes"] = row["notes"]
        if row.get("arm") and row["arm"] not in run["arms"]:
            run["arms"].append(row["arm"])
        if row.get("n_questions") is not None:
            run["n_questions"] = max(run["n_questions"] or 0, row["n_questions"])
        if row.get("grading") is not None and (run["grading"] is None or row["grading"] > run["grading"]):
            run["grading"] = row["grading"]
            run["scoring_version"] = row.get("scoring_version")
        for field in ("series", "judge", "benchmark"):
            if row.get(field) and not run[field]:
                run[field] = row[field]
    return sorted(grouped.values(), key=lambda r: r["started_at"] or "", reverse=True)


def arm_summary(rows: Sequence[dict], total_tokens: int | None) -> dict:
    curated = [r for r in rows if is_curated(r.get("category"))]
    latencies = [r.get("latency_s") for r in rows]
    return {
        "n": len(rows),
        "passed": rate(r.get("passed") for r in rows),
        "correct": rate(r.get("correct") for r in rows),
        "route_ok": rate(r.get("route_ok") for r in rows),
        "scope_ok": rate(r.get("scope_ok") for r in rows),
        "behavior_ok": rate(r.get("behavior_ok") for r in rows),
        "clear": rate(r.get("clear") for r in rows),
        "no_leak": rate(r.get("no_leak") for r in rows),
        "latency_p50_s": percentile(latencies, 0.5),
        "latency_p95_s": percentile(latencies, 0.95),
        "errors": sum(1 for r in rows if r.get("error")),
        "out_of_scope_touches": sum(1 for r in rows if r.get("out_of_scope_tables")),
        "unverified_sql_turns": sum(1 for r in rows if r.get("unverified_sql")),
        "false_fallback": rate(bool(FALLBACK_ROUTES & set(r.get("routes") or [])) for r in curated),
        "total_tokens": total_tokens,
        # A stored 0 means nothing was reported for the arm, so it is shown as unknown, not as zero.
        "supervisor_tokens_per_turn": average(r.get("supervisor_tokens") for r in rows) or None,
        "agent_tokens_per_turn": average(r.get("agent_tokens") for r in rows) or None,
    }


def arm_tokens(gateway: Sequence[dict], arm: str) -> int | None:
    values = [g.get("total_tokens") for g in gateway if g.get("arm") == arm]
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def category_rows(rows: Sequence[dict], arms: Sequence[str], categories: Sequence[str]) -> list[dict]:
    out = []
    for category in categories:
        for arm in arms:
            subset = [r for r in rows if r.get("category") == category and r.get("arm") == arm]
            if not subset:
                continue
            out.append(
                {
                    "category": category,
                    "arm": arm,
                    "n": len(subset),
                    "passed": rate(r.get("passed") for r in subset),
                    "correct": rate(r.get("correct") for r in subset),
                    "scope_ok": rate(r.get("scope_ok") for r in subset),
                    "latency_p50_s": percentile((r.get("latency_s") for r in subset), 0.5),
                }
            )
    return out


def summary(
    run_label: str | None,
    rows: Sequence[dict],
    gateway: Sequence[dict],
    arms: Sequence[str],
    categories: Sequence[str],
) -> dict:
    per_arm = {}
    for arm in arms:
        subset = [r for r in rows if r.get("arm") == arm]
        per_arm[arm] = arm_summary(subset, arm_tokens(gateway, arm))
    return {
        "run_label": run_label,
        "arms": per_arm,
        "by_category": category_rows(rows, arms, categories),
    }


def governance(run_label: str | None, rows: Sequence[dict], gateway: Sequence[dict], arms: Sequence[str]) -> dict:
    touches: dict[tuple[str, str], dict] = {}
    for row in rows:
        for table in row.get("out_of_scope_tables") or []:
            key = (row["arm"], table)
            entry = touches.setdefault(key, {"questions": set(), "example_question_id": row["question_id"]})
            entry["questions"].add(row["question_id"])
    touch_list = [
        {
            "arm": arm,
            "table": table,
            "questions": len(entry["questions"]),
            "example_question_id": min(entry["questions"]),
        }
        for (arm, table), entry in touches.items()
    ]
    touch_list.sort(
        key=lambda t: (arms.index(t["arm"]) if t["arm"] in arms else len(arms), -t["questions"], t["table"])
    )

    sandbox = {
        arm: sum(1 for r in rows if r["arm"] == arm and SANDBOX_ROUTE in (r.get("routes") or [])) for arm in arms
    }

    refusals = {}
    for arm in arms:
        asked = [r for r in rows if r["arm"] == arm and r.get("expected_behavior") == REFUSE]
        refusals[arm] = {"expected": len(asked), "held": sum(1 for r in asked if r.get("behavior_ok"))}

    gateway_rows = [
        {
            "arm": g["arm"],
            "service_name": g.get("service_name"),
            "service_type": g.get("service_type"),
            "tool_name": g.get("tool_name"),
            "calls": g.get("calls"),
            "total_tokens": g.get("total_tokens"),
            "avg_latency_ms": None if g.get("avg_latency_ms") is None else round(float(g["avg_latency_ms"])),
        }
        for g in gateway
    ]
    return {
        "run_label": run_label,
        "touches": touch_list,
        "sandbox_uses": sandbox,
        "refusals": refusals,
        "gateway": gateway_rows,
    }


def _outcome_counts(outcomes: Iterable[str]) -> dict[str, int]:
    counts = Counter(outcomes)
    order = {name: index for index, name in enumerate(DIRECT_OUTCOMES)}
    return {name: counts[name] for name in sorted(counts, key=lambda n: (order.get(n, len(order)), n))}


def direct_test_grid(rows: Sequence[dict]) -> dict:
    """The latest run of the direct test, as conditions and requests. Rows are the direct_test_runs rows."""
    if not rows:
        return {"test_id": None, "started_at": None, "conditions": [], "requests": []}
    latest = max(rows, key=lambda r: str(r.get("started_at") or ""))
    current = [r for r in rows if r["test_id"] == latest["test_id"]]

    conditions = []
    for condition in DIRECT_CONDITIONS:
        subset = [r for r in current if r["condition"] == condition]
        if subset:
            conditions.append(
                {
                    "condition": condition,
                    "samples": len(subset),
                    "ok": sum(1 for r in subset if r.get("ok")),
                    "outcomes": _outcome_counts(r["outcome"] for r in subset),
                }
            )

    requests = []
    for request_id in sorted({r["request_id"] for r in current}):
        mine = [r for r in current if r["request_id"] == request_id]
        cells = {}
        for condition in DIRECT_CONDITIONS:
            cell_rows = [r for r in mine if r["condition"] == condition]
            if not cell_rows:
                continue
            cells[condition] = {
                "samples": len(cell_rows),
                "outcomes": _outcome_counts(r["outcome"] for r in cell_rows),
                "out_of_scope_tables": sorted({t for r in cell_rows for t in r.get("out_of_scope_tables") or []}),
                "leak_hits": sorted({h for r in cell_rows for h in r.get("leak_hits") or []}),
                "rejected": sum(r.get("rejected_count") or 0 for r in cell_rows),
            }
        requests.append({"id": request_id, "kind": mine[0]["kind"], "question": mine[0]["question"], "cells": cells})

    return {
        "test_id": latest["test_id"],
        "started_at": latest["started_at"],
        "conditions": conditions,
        "requests": requests,
    }


def filter_results(
    rows: Sequence[dict],
    arm: str | None = None,
    category: str | None = None,
    passed: bool | None = None,
) -> list[dict]:
    out = []
    for row in rows:
        if arm and row["arm"] != arm:
            continue
        if category and row["category"] != category:
            continue
        if passed is not None and bool(row.get("passed")) != passed:
            continue
        out.append({field: row.get(field) for field in LIST_FIELDS})
    return out


def question_set(rows: Sequence[dict], arms: Sequence[str]) -> list[dict]:
    """The questions of a run with their reference answer, one row for each question."""
    out: dict[str, dict] = {}
    for row in rows:
        entry = out.setdefault(
            row["question_id"],
            {**{field: row.get(field) for field in QUESTION_FIELDS}, "gold_sql": None, "gold_result": None,
             "passed": {arm: None for arm in arms}},
        )  # fmt: skip
        entry["gold_sql"] = entry["gold_sql"] or row.get("gold_sql")
        if entry["gold_result"] is None:
            entry["gold_result"] = row.get("gold_result")
        if row["arm"] in entry["passed"]:
            entry["passed"][row["arm"]] = row.get("passed")
    return sorted(out.values(), key=lambda q: q["question_id"])


def question_detail(rows: Sequence[dict], arms: Sequence[str], question_id: str) -> dict | None:
    matching = [r for r in rows if r["question_id"] == question_id]
    if not matching:
        return None
    shared = {field: matching[0].get(field) for field in QUESTION_FIELDS}
    by_arm = {r["arm"]: r for r in matching}
    return {"question": shared, "arms": {arm: by_arm[arm] for arm in arms if arm in by_arm}}
