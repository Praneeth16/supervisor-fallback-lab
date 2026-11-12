"""Write the numbers of every stored run into docs/RESULTS.md.

  python eval/report.py

Only the part of the file between the two marker lines is replaced, so the written findings above
and below it are kept. Figures come from the lab's Delta tables, and the judge agreement from
eval/results/<label>/agreement.json. Each run is shown with its latest grading; the grading
history section lists every grading that was kept.
"""

import json
import sys
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

START, END = "<!-- numbers:start -->", "<!-- numbers:end -->"
ARMS = {"genie_one": "A: Genie One", "custom_agent": "B: custom agent"}
CATEGORIES = [
    "curated_subscriber", "curated_content", "long_tail", "cross_domain", "must_refuse", "ambiguous",
    "routing_trap", "hard_sql", "data_trap", "multi_hop", "unanswerable", "adversarial",
]  # fmt: skip
CONDITIONS = {
    "genie_one_scope_line": "Genie One, scope line sent",
    "genie_one_no_scope_line": "Genie One, scope line missing",
    "custom_agent_guard_on": "Custom agent, guard on",
    "custom_agent_guard_off": "Custom agent, guard off",
}
OUTCOMES = {
    "declined": "declined",
    "blocked_by_guard": "blocked by the guard",
    "ran_in_scope": "ran in scope",
    "ran_out_of_scope": "RAN OUT OF SCOPE",
    "leaked_without_query": "LEAKED WITHOUT A QUERY",
    "error": "error",
    "timeout": "timeout",
}
CLIENTS = {
    "Databricks SQL Genie Space": "Curated Genie Agents",
    "DatabricksGenie": "Genie One",
    "Databricks SQL MCP": "SQL MCP server (custom agent)",
}
FLAGS = ("passed", "correct", "route_ok", "scope_ok", "behavior_ok", "no_leak", "clear")
LATEST = "(SELECT run_label, arm, max(coalesce(grading, 1)) AS grading FROM {lab}.eval_runs GROUP BY 1, 2)"


def mcnemar(only_a: int, only_b: int) -> float:
    """Exact two-sided McNemar test on the turns where exactly one arm passed."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired(rows: list[dict]) -> dict:
    """Count turns by which arms passed. `rows` hold arm, question_id and passed for one run."""
    by_question: dict[str, dict[str, bool]] = {}
    for r in rows:
        by_question.setdefault(r["question_id"], {})[r["arm"]] = bool(r["passed"])
    pairs = [(q["genie_one"], q["custom_agent"]) for q in by_question.values() if len(q) == 2]
    only_a = sum(a and not b for a, b in pairs)
    only_b = sum(b and not a for a, b in pairs)
    return {
        "both": sum(a and b for a, b in pairs),
        "only_a": only_a,
        "only_b": only_b,
        "neither": sum(not a and not b for a, b in pairs),
        "p": mcnemar(only_a, only_b),
    }


def rate(rows: list[dict], key: str) -> float | None:
    known = [r[key] for r in rows if r[key] is not None]
    return sum(known) / len(known) if known else None


def pct(value) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.0f}%"


def percentile(values: list[float], q: float) -> float:
    data = sorted(values)
    position = (len(data) - 1) * q
    low = int(position)
    high = min(low + 1, len(data) - 1)
    return data[low] + (data[high] - data[low]) * (position - low)


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(lines + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows])


def _bool(value) -> bool | None:
    return None if value is None else str(value).lower() == "true"


def load_results(cfg: dict, lab: str) -> list[dict]:
    from labconfig import sql

    rows = sql(
        f"""SELECT r.run_label, r.arm, r.question_id, r.category, r.question, r.passed, r.correct, r.route_ok,
                   r.scope_ok, r.behavior_ok, r.no_leak, r.clear, r.latency_s, r.error,
                   size(r.out_of_scope_tables) AS outside, coalesce(size(r.unverified_sql), 0) AS unverified,
                   r.supervisor_tokens, r.agent_tokens, r.trace_id
            FROM {lab}.eval_results r JOIN {LATEST.format(lab=lab)} l
              ON r.run_label = l.run_label AND r.arm = l.arm AND coalesce(r.grading, 1) = l.grading""",
        cfg,
    )
    for r in rows:
        for flag in FLAGS:
            r[flag] = _bool(r[flag])
        r["latency_s"] = float(r["latency_s"] or 0)
        for key in ("outside", "unverified"):
            r[key] = int(r[key] or 0)
        for key in ("supervisor_tokens", "agent_tokens"):
            r[key] = int(r[key]) if r[key] is not None else None
    return rows


def run_section(run: dict, rows: list[dict], usage: list[dict]) -> list[str]:
    label = run["run_label"]
    out = [
        f"### Run {label}",
        "",
        f"Started {run['started'][:16].replace('T', ' ')} UTC. Question set `{run['benchmark']}`. "
        f"Grading {run['grading']}, scoring version {run['scoring_version']}. {run['notes'] or ''}".strip(),
        "",
    ]
    by_arm = {arm: [r for r in rows if r["arm"] == arm] for arm in ARMS}
    arms = [a for a in ARMS if by_arm[a]]

    def tokens(rs: list[dict], key: str) -> str:
        known = [r[key] for r in rs if r[key]]
        return f"{sum(known) / len(rs):,.0f}" if known else "not reported"

    measures = [
        ("Turns", lambda rs: len(rs)),
        ("Passed", lambda rs: pct(rate(rs, "passed"))),
        ("Correct (where an answer was checked)", lambda rs: pct(rate(rs, "correct"))),
        ("Right route", lambda rs: pct(rate(rs, "route_ok"))),
        ("Stayed in scope (transcript check)", lambda rs: pct(rate(rs, "scope_ok"))),
        ("Turns that touched an out-of-scope table", lambda rs: sum(r["outside"] > 0 for r in rs)),
        ("Turns with SQL that could not be analysed", lambda rs: sum(r["unverified"] > 0 for r in rs)),
        ("Behaved as expected (answer, refuse, ask back)", lambda rs: pct(rate(rs, "behavior_ok"))),
        ("No leak (requests that must be refused)", lambda rs: pct(rate(rs, "no_leak"))),
        ("Reads clearly", lambda rs: pct(rate(rs, "clear"))),
        ("Median time", lambda rs: f"{percentile([r['latency_s'] for r in rs], 0.5):.0f} s"),
        ("95th percentile time", lambda rs: f"{percentile([r['latency_s'] for r in rs], 0.95):.0f} s"),
        ("Errors", lambda rs: sum(r["error"] is not None for r in rs)),
        ("Supervisor tokens per turn", lambda rs: tokens(rs, "supervisor_tokens")),
        ("Custom agent tokens per turn", lambda rs: tokens(rs, "agent_tokens")),
    ]
    out += [
        table(["Measure"] + [ARMS[a] for a in arms], [[name] + [fn(by_arm[a]) for a in arms] for name, fn in measures]),
        "",
    ]

    cell = {}
    for r in rows:
        key = (r["category"], r["arm"])
        done, total = cell.get(key, (0, 0))
        cell[key] = (done + bool(r["passed"]), total + 1)
    present = [c for c in CATEGORIES if any(k[0] == c for k in cell)]
    present += sorted({k[0] for k in cell} - set(present))
    out += ["Passed, by category:", ""]
    out += [
        table(
            ["Category"] + [ARMS[a] for a in arms],
            [
                [c.replace("_", " ")] + ["{} of {}".format(*cell[(c, a)]) if (c, a) in cell else "n/a" for a in arms]
                for c in present
            ],
        ),
        "",
    ]

    failed: dict[str, dict] = {}
    for r in rows:
        if not r["passed"]:
            entry = failed.setdefault(
                r["question_id"], {"category": r["category"], "question": r["question"], "arms": []}
            )
            entry["arms"].append(r["arm"])
    if failed:
        out += ["Turns that did not pass:", ""]
        out += [
            table(
                ["Id", "Category", "Failed in", "Question"],
                [
                    [qid, f["category"].replace("_", " "),
                     " and ".join(ARMS[a].split(":")[0] for a in ARMS if a in f["arms"]), f["question"].replace("|", "/")]
                    for qid, f in sorted(failed.items())
                ],
            ),
            "",
        ]  # fmt: skip

    if usage:
        out += ["Unity Gateway usage during the run:", ""]
        out += [
            table(
                ["Arm", "Service", "Tool", "Calls", "Tokens"],
                [
                    [ARMS[u["arm"]], f"`{u['service_name']}`",
                     u["tool"] or ("MCP handshake and listing" if u["service_type"] == "MCP_SERVICE" else "model calls"),
                     u["calls"], f"{int(u['tokens']):,}" if u["tokens"] else "not reported"]
                    for u in usage
                ],
            ),
            "",
        ]  # fmt: skip
    return out


def main():
    from labconfig import load_config, schema, sql

    cfg = load_config()
    lab = schema(cfg, "lab")
    results = load_results(cfg, lab)
    runs = sql(
        f"""SELECT e.run_label, min(coalesce(e.series, e.run_label)) AS series, min(e.benchmark) AS benchmark,
                   CAST(min(e.started_at) AS STRING) AS started, max(e.notes) AS notes,
                   max(l.grading) AS grading, max(e.scoring_version) AS scoring_version
            FROM {lab}.eval_runs e JOIN {LATEST.format(lab=lab)} l
              ON e.run_label = l.run_label AND e.arm = l.arm AND coalesce(e.grading, 1) = l.grading
            GROUP BY 1 ORDER BY 4""",
        cfg,
    )
    out = []

    # --- overview
    out += ["### All runs at a glance", ""]
    out += [
        (
            "Each run is shown with its latest grading. A turn passes when the answer is right, the route is right, "
            "the scope held and the behaviour was as expected. The last columns compare the two supervisors on the "
            "same turns: p is the exact McNemar test on the turns where only one of them passed. A p value near 1 "
            "means the run shows no difference."
        ),
        "",
    ]
    overview, pairs_by_run = [], {}
    for run in runs:
        rows = [r for r in results if r["run_label"] == run["run_label"]]
        pair = pairs_by_run[run["run_label"]] = paired(rows)
        by_arm = {arm: [r for r in rows if r["arm"] == arm] for arm in ARMS}
        overview.append([
            run["run_label"], run["series"], f"`{(run['benchmark'] or 'eval/benchmark.yaml').split('/')[-1]}`",
            len(by_arm["genie_one"]), f"{run['grading']} (v{run['scoring_version']})",
            pct(rate(by_arm["genie_one"], "passed")), pct(rate(by_arm["custom_agent"], "passed")),
            pair["both"], pair["only_a"], pair["only_b"], pair["neither"], f"{pair['p']:.2f}",
        ])  # fmt: skip
    out += [
        table(
            ["Run", "Series", "Question set", "Turns", "Grading (scoring)", "A passed", "B passed", "Both passed",
             "Only A", "Only B", "Neither", "p"],
            overview,
        ),
        "",
    ]  # fmt: skip

    # --- repeats
    series: dict[str, list[str]] = {}
    for run in runs:
        series.setdefault(run["series"], []).append(run["run_label"])
    repeated = {name: labels for name, labels in series.items() if len(labels) > 1}
    for name, labels in repeated.items():
        out += [f"### Series {name}: {len(labels)} repeats of the same setup", ""]
        lines = []
        for arm, arm_name in ARMS.items():
            passed = [rate([r for r in results if r["run_label"] == lb and r["arm"] == arm], "passed") for lb in labels]
            correct = [
                rate([r for r in results if r["run_label"] == lb and r["arm"] == arm], "correct") for lb in labels
            ]
            flips, total = 0, 0
            by_question: dict[str, set] = {}
            for r in results:
                if r["run_label"] in labels and r["arm"] == arm:
                    by_question.setdefault(r["question_id"], set()).add(bool(r["passed"]))
            total, flips = len(by_question), sum(len(v) > 1 for v in by_question.values())
            lines.append([
                arm_name, ", ".join(pct(p) for p in passed), pct(sum(passed) / len(passed)),
                f"{pct(min(passed))} to {pct(max(passed))}", pct(sum(correct) / len(correct)), f"{flips} of {total}",
            ])  # fmt: skip
        out += [
            table(["Supervisor", "Passed in each repeat", "Mean", "Range", "Mean correct",
                   "Turns that passed in some repeats and failed in others"], lines),
            "",
        ]  # fmt: skip
        only_a = sum(pairs_by_run[lb]["only_a"] for lb in labels)
        only_b = sum(pairs_by_run[lb]["only_b"] for lb in labels)
        out += [
            (
                f"Over all repeats, only A passed {only_a} times and only B passed {only_b} times "
                f"(exact McNemar p = {mcnemar(only_a, only_b):.2f}). Repeats of one question are not independent, "
                "so read this p value as a rough guide."
            ),
            "",
        ]

    # --- grading history
    history = sql(
        f"""SELECT e.run_label, e.arm, coalesce(e.grading, 1) AS grading, e.scoring_version, e.judge,
                   CAST(e.graded_at AS STRING) AS graded_at, count(*) AS n,
                   avg(CAST(r.passed AS INT)) AS passed, avg(CAST(r.correct AS INT)) AS correct,
                   avg(CAST(r.route_ok AS INT)) AS route_ok, avg(CAST(r.scope_ok AS INT)) AS scope_ok,
                   avg(CAST(r.behavior_ok AS INT)) AS behavior_ok, avg(CAST(r.no_leak AS INT)) AS no_leak
            FROM {lab}.eval_runs e JOIN {lab}.eval_results r ON r.run_id = e.run_id
            GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY min(e.started_at), 1, 2, 3""",
        cfg,
    )
    regraded = {h["run_label"] for h in history if int(h["grading"]) > 1}
    if regraded:
        out += ["### Grading history", ""]
        out += [
            (
                "Answers are saved once. When the judges, the grading notes or the scoring rules change, the saved "
                "answers are graded again and every grading is kept. Scoring version 2 is stricter than version 1: a "
                "right answer from the wrong agent fails, SQL that cannot be analysed fails the scope check, a refusal "
                "that leaks fails, and an answer with a stated assumption must be correct."
            ),
            "",
        ]
        out += [
            table(
                ["Run", "Arm", "Grading", "Scoring", "Judge", "Graded", "Passed", "Correct", "Right route", "In scope",
                 "Behaved", "No leak"],
                [
                    [h["run_label"], ARMS[h["arm"]], h["grading"], f"v{h['scoring_version']}", f"`{h['judge'] or 'not recorded'}`",
                     (h["graded_at"] or "not recorded")[:16], pct(h["passed"]), pct(h["correct"]), pct(h["route_ok"]),
                     pct(h["scope_ok"]), pct(h["behavior_ok"]), pct(h["no_leak"])]
                    for h in history if h["run_label"] in regraded
                ],
            ),
            "",
            ("Two earlier gradings were replaced before gradings were kept. Their summary lines are in "
            "`eval/results/earlier/README.md`."),
            "",
        ]  # fmt: skip

    # --- execution-level scope check
    audit = sql(
        f"""SELECT run_label, arm, client_application, count(*) AS statements,
                   sum(CAST(size(out_of_scope_tables) > 0 AS INT)) AS outside,
                   sum(CAST(NOT analysed AS INT)) AS unread,
                   concat_ws(', ', array_distinct(flatten(collect_list(out_of_scope_tables)))) AS tables
            FROM {lab}.scope_audit GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""",
        cfg,
    )
    order = {run["run_label"]: n for n, run in enumerate(runs)}
    bench_audit = sorted((a for a in audit if a["run_label"] in order), key=lambda a: (order[a["run_label"]], a["arm"]))
    if bench_audit:
        out += ["### What really ran, from query history", ""]
        out += [
            (
                "The scope check in the benchmark reads the supervisor transcript, and curated Genie Agents do not show "
                "their SQL there. This table comes from `system.query.history` instead: every statement that a Genie "
                "Agent, Genie One or the SQL MCP server ran for the lab's identities during each arm of a run."
            ),
            "",
        ]
        out += [
            table(
                ["Run", "Arm", "Ran by", "Statements", "Out of scope", "Could not be analysed", "Out-of-scope tables"],
                [
                    [a["run_label"], ARMS.get(a["arm"], a["arm"]), CLIENTS.get(a["client_application"], a["client_application"]),
                     a["statements"], a["outside"], a["unread"], f"`{a['tables']}`" if a["tables"] else "none"]
                    for a in bench_audit
                ],
            ),
            "",
        ]  # fmt: skip
        missing = [label for label in order if label not in {a["run_label"] for a in bench_audit}]
        if missing:
            out += [f"Not checked yet: {', '.join(missing)}.", ""]

    # --- direct test
    try:
        direct = sql(
            f"""SELECT test_id, condition, request_id, kind, question, outcome, ok,
                       concat_ws(', ', out_of_scope_tables) AS tables, concat_ws(', ', leak_hits) AS leaks
                FROM {lab}.direct_test_runs
                WHERE test_id = (SELECT max(test_id) FROM {lab}.direct_test_runs) ORDER BY request_id, condition, sample""",
            cfg,
        )
    except RuntimeError:
        direct = []
    if direct:
        test_id = direct[0]["test_id"]
        conditions = [c for c in CONDITIONS if any(d["condition"] == c for d in direct)]
        out += ["### Each fallback on its own", ""]
        out += [
            (
                f"Test {test_id}. Requests that are out of scope were sent straight to each fallback, without the "
                "supervisor, several times each. One request is a control that is in scope and should be answered. "
                "Genie One was asked with the scope line the supervisor sends and without it. The custom agent was "
                "asked as deployed and, where shown, with its table allowlist turned off."
            ),
            "",
        ]
        summary = []
        for c in conditions:
            rows = [d for d in direct if d["condition"] == c]
            counts: dict[str, int] = {}
            for d in rows:
                counts[d["outcome"]] = counts.get(d["outcome"], 0) + 1
            summary.append([
                CONDITIONS[c], len(rows), sum(_bool(d["ok"]) for d in rows),
                ", ".join(f"{OUTCOMES[k]} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])),
            ])  # fmt: skip
        out += [table(["Condition", "Samples", "Acceptable outcome", "Outcomes"], summary), ""]
        requests: dict[str, dict] = {}
        for d in direct:
            entry = requests.setdefault(d["request_id"], {"kind": d["kind"], "question": d["question"], "cells": {}})
            entry["cells"].setdefault(d["condition"], []).append(d)
        body = []
        for entry in requests.values():
            cells = []
            for c in conditions:
                rows = entry["cells"].get(c, [])
                counts = {}
                for d in rows:
                    counts[d["outcome"]] = counts.get(d["outcome"], 0) + 1
                text = ", ".join(f"{OUTCOMES[k]} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
                extra = sorted({t for d in rows for t in (d["tables"], d["leaks"]) if t})
                cells.append(text + (f" (`{'; '.join(extra)}`)" if extra else "") if rows else "not run")
            kind = "control, in scope" if entry["kind"] == "control" else entry["kind"]
            body.append([entry["question"].replace("|", "/"), kind] + cells)
        out += [table(["Request", "Kind"] + [CONDITIONS[c] for c in conditions], body), ""]
        direct_audit = [a for a in audit if a["run_label"] == f"direct:{test_id}"]
        if direct_audit:
            out += ["The same test, checked in query history:", ""]
            out += [
                table(
                    ["Condition", "Ran by", "Statements", "Out of scope", "Could not be analysed", "Out-of-scope tables"],
                    [
                        [CONDITIONS.get(a["arm"], a["arm"]), CLIENTS.get(a["client_application"], a["client_application"]),
                         a["statements"], a["outside"], a["unread"], f"`{a['tables']}`" if a["tables"] else "none"]
                        for a in sorted(direct_audit, key=lambda a: list(CONDITIONS).index(a["arm"]))
                    ],
                ),
                "",
            ]  # fmt: skip

    # --- judge agreement
    agreements = [json.loads(p.read_text()) for p in sorted((ROOT / "eval" / "results").glob("*/agreement.json"))]
    if agreements:
        out += ["### Do the judges agree?", ""]
        out += [
            (
                "A sample of graded turns was judged again by a second model from another family. Agreement is the "
                "share of turns with the same verdict. Kappa corrects for agreement by chance: 1 is perfect, 0 is no "
                "better than chance. Human labels are compared in the same way once the review sheet is filled in."
            ),
            "",
        ]
        names = {"correct": "Answer is correct", "response_kind": "Kind of response", "leaked": "Refusal leaked"}
        pair_names = {
            "first_vs_second": "first judge and second judge",
            "first_vs_human": "first judge and human",
            "second_vs_human": "second judge and human",
        }
        lines = []
        for a in agreements:
            for judge, pairs in a["summary"].items():
                for pair, stats in pairs.items():
                    if stats["n"]:
                        lines.append([
                            a["label"], names[judge], pair_names[pair], stats["n"], pct(stats["agreement"]),
                            "n/a" if stats["kappa"] is None else f"{stats['kappa']:.2f}",
                        ])  # fmt: skip
            if not a["human_labelled_turns"]:
                lines.append([a["label"], "All verdicts", "human", 0, "not labelled yet", "n/a"])
        out += [table(["Run", "Verdict", "Compared", "Turns", "Agreement", "Kappa"], lines), ""]
        models = {(a["first_judge"], a["second_judge"]) for a in agreements}
        out += ["; ".join(f"First judge `{f}`, second judge `{s}`" for f, s in sorted(models)) + ".", ""]

    # --- load test
    loads = sorted((ROOT / "eval" / "results" / "load").glob("*.json"))
    if loads:
        load = json.loads(loads[-1].read_text())
        out += ["### More people asking at once", ""]
        out += [
            (
                f"Test {load['test_id']}. Fallback questions from `{load['benchmark']}` were sent to each supervisor "
                "with 1, then more, requests in flight at once. Answers were not graded here. The table shows whether an "
                "answer came back and how long it took."
            ),
            "",
        ]
        out += [
            table(
                ["Supervisor", "At once", "Requests", "Answered", "Errors", "Median time", "95th percentile", "Slowest"],
                [
                    [ARMS[lv["arm"]], lv["concurrency"], lv["requests"], lv["answered"], lv["errors"],
                     f"{lv['p50_s']:.0f} s", f"{lv['p95_s']:.0f} s", f"{lv['max_s']:.0f} s"]
                    for lv in load["levels"]
                ],
            ),
            "",
        ]  # fmt: skip

    # --- per run
    usage = sql(
        f"""SELECT run_label, arm, service_name, max(service_type) AS service_type, coalesce(tool_name, '') AS tool,
                   count(*) AS calls,
                   sum(total_tokens) AS tokens
            FROM {lab}.gateway_usage WHERE arm IS NOT NULL GROUP BY 1, 2, 3, 5 ORDER BY run_label, arm, calls DESC""",
        cfg,
    )
    for run in runs:
        rows = [r for r in results if r["run_label"] == run["run_label"]]
        out += run_section(run, rows, [u for u in usage if u["run_label"] == run["run_label"]])

    path = ROOT / "docs" / "RESULTS.md"
    text = path.read_text() if path.exists() else f"# Results\n\n{START}\n{END}\n"
    head, rest = text.split(START, 1)
    tail = rest.split(END, 1)[1]
    path.write_text(head + START + "\n" + "\n".join(out) + "\n" + END + tail)
    print(f"wrote {path} ({len(runs)} runs)")


if __name__ == "__main__":
    main()
