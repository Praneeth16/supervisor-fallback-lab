from lab_app.summary import (
    category_rows,
    direct_test_grid,
    filter_results,
    governance,
    group_runs,
    percentile,
    question_detail,
    rate,
    summary,
)

ARMS = ("genie_one", "custom_agent")
CATEGORIES = ("curated_subscriber", "long_tail", "must_refuse")


def row(**overrides):
    base = {
        "run_label": "v1",
        "arm": "genie_one",
        "question_id": "q001",
        "category": "curated_subscriber",
        "expected_behavior": "answer",
        "routes": ["genie:subscribers_revenue"],
        "tables": [],
        "out_of_scope_tables": [],
        "latency_s": 10.0,
        "error": None,
        "correct": True,
        "route_ok": True,
        "scope_ok": True,
        "behavior_ok": True,
        "clear": True,
        "passed": True,
        "thread_id": None,
        "turn": 1,
        "persona": "Analyst",
        "question": "q",
        "expected_route": "genie:subscribers_revenue",
    }
    base.update(overrides)
    return base


def test_rate_ignores_none_and_returns_none_when_empty():
    assert rate([True, False, None, True]) == 0.6667
    assert rate([None, None]) is None
    assert rate([]) is None


def test_percentile_interpolates_between_ranks():
    values = [10, 20, 30, 40]
    assert percentile(values, 0.5) == 25.0
    assert percentile(values, 0.95) == 38.5
    assert percentile([None], 0.5) is None
    assert percentile([7.0], 0.95) == 7.0


def test_group_runs_collapses_arms_and_sorts_newest_first():
    rows = [
        {
            "run_label": "v1",
            "arm": "genie_one",
            "started_at": "2026-11-06T09:00:00Z",
            "notes": "first",
            "n_questions": 24,
        },
        {
            "run_label": "v1",
            "arm": "custom_agent",
            "started_at": "2026-11-06T09:05:00Z",
            "notes": None,
            "n_questions": 24,
        },
        {
            "run_label": "v2",
            "arm": "genie_one",
            "started_at": "2026-11-10T16:40:00Z",
            "notes": "second",
            "n_questions": 24,
        },
    ]
    runs = group_runs(rows)
    assert [r["run_label"] for r in runs] == ["v2", "v1"]
    assert runs[1]["arms"] == ["genie_one", "custom_agent"]
    assert runs[1]["started_at"] == "2026-11-06T09:00:00Z"
    assert runs[1]["notes"] == "first"
    assert runs[1]["n_questions"] == 24


def test_arm_summary_counts_false_fallback_only_on_curated_rows():
    rows = [
        row(routes=["genie_one"]),
        row(routes=["genie:subscribers_revenue"]),
        row(category="long_tail", routes=["genie_one"], latency_s=50.0),
    ]
    result = summary("v1", rows, [], ARMS, CATEGORIES)["arms"]["genie_one"]
    assert result["n"] == 3
    assert result["false_fallback"] == 0.5
    assert result["latency_p50_s"] == 10.0


def test_errors_and_out_of_scope_touches_are_counted():
    rows = [
        row(error="timeout", correct=False, passed=False, latency_s=600.0, routes=[]),
        row(out_of_scope_tables=["x.talent.t"], scope_ok=False, passed=False),
        row(),
    ]
    result = summary("v1", rows, [], ARMS, CATEGORIES)["arms"]["genie_one"]
    assert result["errors"] == 1
    assert result["out_of_scope_touches"] == 1
    assert result["scope_ok"] == 0.6667
    assert result["correct"] == 0.6667


def test_total_tokens_sums_gateway_rows_for_the_arm_and_is_null_without_numbers():
    gateway = [
        {"arm": "custom_agent", "total_tokens": 100},
        {"arm": "custom_agent", "total_tokens": None},
        {"arm": "custom_agent", "total_tokens": 50},
        {"arm": "genie_one", "total_tokens": None},
    ]
    out = summary("v1", [], gateway, ARMS, CATEGORIES)["arms"]
    assert out["custom_agent"]["total_tokens"] == 150
    assert out["genie_one"]["total_tokens"] is None


def test_category_rows_skip_empty_combinations():
    rows = [row(category="long_tail", arm="custom_agent")]
    out = category_rows(rows, ARMS, CATEGORIES)
    assert [(r["category"], r["arm"]) for r in out] == [("long_tail", "custom_agent")]


def test_governance_counts_touches_refusals_and_sandbox_use():
    rows = [
        row(question_id="q016", out_of_scope_tables=["a.talent.roster"], scope_ok=False),
        row(question_id="q020", out_of_scope_tables=["a.talent.roster"], scope_ok=False, arm="genie_one"),
        row(
            question_id="q019",
            out_of_scope_tables=["a.hr.roster"],
            expected_behavior="refuse",
            behavior_ok=True,
            routes=["sandbox"],
            scope_ok=False,
        ),
        row(question_id="q018", expected_behavior="refuse", behavior_ok=False, arm="custom_agent"),
    ]
    out = governance(
        "v1",
        rows,
        [
            {
                "arm": "genie_one",
                "service_name": "s",
                "service_type": "MCP_SERVICE",
                "tool_name": "genie_ask",
                "calls": 3,
                "total_tokens": None,
                "avg_latency_ms": 311.4,
            }
        ],
        ARMS,
    )
    roster = [t for t in out["touches"] if t["table"] == "a.talent.roster"]
    assert roster == [{"arm": "genie_one", "table": "a.talent.roster", "questions": 2, "example_question_id": "q016"}]
    assert out["sandbox_uses"] == {"genie_one": 1, "custom_agent": 0}
    assert out["refusals"]["genie_one"] == {"expected": 1, "held": 1}
    assert out["refusals"]["custom_agent"] == {"expected": 1, "held": 0}
    assert out["gateway"][0]["avg_latency_ms"] == 311


def test_filter_results_applies_each_filter_and_keeps_contract_fields_only():
    rows = [row(), row(arm="custom_agent", category="long_tail", passed=False, transcript=[1], gold_result=[2])]
    assert len(filter_results(rows)) == 2
    assert [r["arm"] for r in filter_results(rows, arm="custom_agent")] == ["custom_agent"]
    assert [r["category"] for r in filter_results(rows, category="long_tail")] == ["long_tail"]
    failed = filter_results(rows, passed=False)
    assert len(failed) == 1 and "transcript" not in failed[0] and "gold_result" not in failed[0]


def test_question_detail_puts_both_arms_side_by_side():
    rows = [row(), row(arm="custom_agent", passed=False)]
    detail = question_detail(rows, ARMS, "q001")
    assert detail["question"]["question_id"] == "q001"
    assert set(detail["arms"]) == {"genie_one", "custom_agent"}
    assert question_detail(rows, ARMS, "q999") is None


def test_group_runs_takes_the_highest_grading_and_its_scoring_version():
    rows = [
        {
            "run_label": "v2",
            "arm": "custom_agent",
            "started_at": "2026-11-10T16:40:00Z",
            "grading": 1,
            "scoring_version": "1.3",
            "judge": "judge-a",
            "series": "lab",
            "benchmark": "eval/benchmark.yaml",
        },
        {
            "run_label": "v2",
            "arm": "genie_one",
            "started_at": "2026-11-10T16:40:00Z",
            "grading": 2,
            "scoring_version": "1.4",
            "judge": "judge-a",
            "series": None,
            "benchmark": None,
        },
    ]
    (run,) = group_runs(rows)
    assert run["grading"] == 2
    assert run["scoring_version"] == "1.4"
    assert (run["series"], run["judge"], run["benchmark"]) == ("lab", "judge-a", "eval/benchmark.yaml")


def test_arm_summary_reports_leaks_unverified_sql_and_tokens_per_turn():
    rows = [
        row(no_leak=True, supervisor_tokens=1000, agent_tokens=None, unverified_sql=[]),
        row(no_leak=False, supervisor_tokens=2000, agent_tokens=500, unverified_sql=["SELEC x FROM"]),
        row(no_leak=None, supervisor_tokens=None, agent_tokens=1500, unverified_sql=None),
    ]
    result = summary("v1", rows, [], ARMS, CATEGORIES)["arms"]["genie_one"]
    assert result["no_leak"] == 0.5
    assert result["unverified_sql_turns"] == 1
    assert result["supervisor_tokens_per_turn"] == 1500.0
    assert result["agent_tokens_per_turn"] == 1000.0


def test_tokens_per_turn_is_null_when_nothing_was_reported():
    result = summary("v1", [row(supervisor_tokens=None, agent_tokens=None)], [], ARMS, CATEGORIES)["arms"]["genie_one"]
    assert result["supervisor_tokens_per_turn"] is None
    assert result["agent_tokens_per_turn"] is None
    assert result["no_leak"] is None


def _direct(
    condition, request_id, outcome, sample=1, ok=True, out=(), leaks=(), rejected=0, started="2026-11-11T08:00"
):
    return {
        "test_id": "rt-b",
        "started_at": started,
        "condition": condition,
        "request_id": request_id,
        "kind": "talent" if request_id.startswith("t") else "control",
        "question": f"question {request_id}",
        "sample": sample,
        "outcome": outcome,
        "ok": ok,
        "out_of_scope_tables": list(out),
        "leak_hits": list(leaks),
        "rejected_count": rejected,
    }


def test_direct_test_grid_is_empty_without_rows():
    assert direct_test_grid([]) == {"test_id": None, "started_at": None, "conditions": [], "requests": []}


def test_direct_test_grid_shows_only_the_latest_test_in_fixed_condition_order():
    old = _direct("genie_one_scope_line", "t1", "ran_out_of_scope", ok=False, out=["x.talent.a"], started="2026-11-01")
    old["test_id"] = "rt-a"
    rows = [
        _direct("custom_agent_guard_off", "t1", "ran_out_of_scope", ok=False, out=["c.hoshi_talent.contract"]),
        _direct("genie_one_scope_line", "t1", "declined", sample=1),
        _direct("genie_one_scope_line", "t1", "declined", sample=2),
        _direct("genie_one_scope_line", "c1", "ran_in_scope"),
        _direct("custom_agent_guard_on", "t1", "blocked_by_guard", rejected=2),
        old,
    ]
    grid = direct_test_grid(rows)
    assert grid["test_id"] == "rt-b"
    assert grid["started_at"] == "2026-11-11T08:00"
    assert [c["condition"] for c in grid["conditions"]] == [
        "genie_one_scope_line",
        "custom_agent_guard_on",
        "custom_agent_guard_off",
    ]
    scope_line = grid["conditions"][0]
    assert scope_line == {
        "condition": "genie_one_scope_line",
        "samples": 3,
        "ok": 3,
        "outcomes": {"declined": 2, "ran_in_scope": 1},
    }
    assert [r["id"] for r in grid["requests"]] == ["c1", "t1"]


def test_direct_test_grid_cells_collect_tables_leaks_and_rejections():
    rows = [
        _direct("custom_agent_guard_on", "t1", "blocked_by_guard", sample=1, rejected=2),
        _direct("custom_agent_guard_on", "t1", "leaked_without_query", sample=2, ok=False, leaks=["fee", "cost"]),
        _direct(
            "custom_agent_guard_on", "t1", "ran_out_of_scope", sample=3, ok=False, out=["b.talent.z", "a.talent.y"]
        ),
    ]
    request = direct_test_grid(rows)["requests"][0]
    assert request["kind"] == "talent"
    assert request["question"] == "question t1"
    cell = request["cells"]["custom_agent_guard_on"]
    assert cell == {
        "samples": 3,
        "outcomes": {"blocked_by_guard": 1, "ran_out_of_scope": 1, "leaked_without_query": 1},
        "out_of_scope_tables": ["a.talent.y", "b.talent.z"],
        "leak_hits": ["cost", "fee"],
        "rejected": 2,
    }
    assert "genie_one_scope_line" not in request["cells"]
