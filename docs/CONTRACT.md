# UI contract

The lab UI is a Databricks App: FastAPI backend in `app/backend`, React frontend in `app/frontend`
built into `app/backend/static`. This file fixes the data the backend reads and the JSON it serves.

## Two arms

| key | label | fallback |
|---|---|---|
| `genie_one` | Supervisor A: Genie Agents + Genie One | Genie One managed MCP, scope set by instructions and skills |
| `custom_agent` | Supervisor B: Genie Agents + custom agent | Custom text-to-SQL agent, scope enforced in code |

Route labels: `genie:subscribers_revenue`, `genie:content_viewing`, `genie_one`, `fallback_agent`,
`sandbox`, `other:<tool>`.

Categories: `curated_subscriber`, `curated_content`, `long_tail`, `cross_domain`, `must_refuse`, `ambiguous`,
`routing_trap`, `hard_sql`, `data_trap`, `multi_hop`, `unanswerable`, `adversarial`.

## Data

Delta tables in `<catalog>.<prefix>lab`, defined in `eval/schema.sql`: `eval_runs`, `eval_results`,
`gateway_usage`, `scope_audit`, `direct_test_runs`. The backend reads them through the SQL Statement
Execution API on the app's warehouse, as the app service principal.

The evaluation tables are append-only. The answers of a run are saved once. Each time they are graded,
rows with the next `grading` number are added, with the `scoring_version` that was used. The UI shows the
latest grading of each run and arm, which it finds through `eval_runs`. A grading's result rows are written
before its run row, so a half-written grading is never shown.

## Backend configuration (environment variables, set in `app/backend/app.yaml`)

`LAB_CATALOG`, `LAB_SCHEMA` (the lab schema name), `DATABRICKS_WAREHOUSE_ID`, `SUPERVISOR_A_ENDPOINT`,
`SUPERVISOR_B_ENDPOINT`, `LAB_BRAND`, `LAB_SCOPE_JSON` (see `/api/config`), `LAB_FIXTURES`
(`1` serves JSON files from `app/backend/fixtures` instead of querying, for local work).

## Shared code already written (do not rewrite)

- `labcore.supervisor.ask(w, endpoint, history) -> Turn(items, latency_s, error, approvals, declined,
  trace_ids, supervisor_tokens)`: calls a supervisor, approves calls to the lab's own app tool and declines
  approval requests for any other tool.
- `labcore.parse.extract(items, allowed_tables) -> Facts(answer, routes, sql, tables, out_of_scope,
  unverified_sql)`. SQL whose tables cannot be determined is listed in `unverified_sql` and counts against
  the scope check.

## API

`GET /api/config`
```json
{"brand": "Hoshi Stream",
 "arms": [{"key": "genie_one", "label": "...", "fallback": "...", "endpoint": "mas-...-endpoint"}, {"key": "custom_agent", "...": "..."}],
 "scope": {"genie_agents": {"subscribers_revenue": ["subscriber", "billing"], "content_viewing": ["content", "distribution"]},
           "fallback": ["rights", "sales", "partner"], "join_only": ["subscriber", "billing", "content", "distribution"], "off_limits": ["talent"]},
 "categories": ["curated_subscriber", "..."],
 "workspace_host": "https://..."}
```

`GET /api/runs` -> `[{"run_label": "v1", "started_at": "...", "notes": "...", "arms": ["genie_one", "custom_agent"], "n_questions": 60,
"series": "v1", "grading": 2, "scoring_version": "2", "judge": "...", "benchmark": "eval/benchmark.yaml"}]`, newest first.
`grading` is the latest grading of the run.

`GET /api/gradings?run_label=v1` -> every grading that was kept for the run, ordered by arm and grading:
`[{"arm", "grading", "scoring_version", "judge", "graded_at", "n", "passed", "correct", "route_ok", "scope_ok",
"behavior_ok", "no_leak"}]`. Rates are 0 to 1 or null.

`GET /api/summary?run_label=v1` (default: newest label)
```json
{"run_label": "v1",
 "arms": {"genie_one": {"n": 60, "passed": 0.72, "correct": 0.70, "route_ok": 0.90, "scope_ok": 0.93, "behavior_ok": 0.85, "clear": 0.88,
                        "latency_p50_s": 31.2, "latency_p95_s": 84.0, "errors": 1, "out_of_scope_touches": 4, "false_fallback": 0.08,
                        "total_tokens": 1234567, "no_leak": 1.0, "unverified_sql_turns": 0,
                        "supervisor_tokens_per_turn": 20500.0, "agent_tokens_per_turn": null},
          "custom_agent": {"...": "..."}},
 "by_category": [{"category": "long_tail", "arm": "genie_one", "n": 14, "passed": 0.64, "correct": 0.6, "scope_ok": 1.0, "latency_p50_s": 40.1}]}
```
Rates are 0 to 1. `correct` is over rows where `correct` is not null. `false_fallback` is the share
of curated-category questions whose routes include `genie_one` or `fallback_agent`.

`GET /api/results?run_label=v1&arm=&category=&passed=` -> list of rows without `transcript`,
`gold_result` and rationales: `question_id, thread_id, turn, category, persona, question, arm,
expected_route, expected_behavior, routes, tables, out_of_scope_tables, latency_s, error, correct,
route_ok, scope_ok, behavior_ok, clear, passed, grading, unverified_sql, no_leak, supervisor_tokens,
agent_tokens`.

`GET /api/results/{run_label}/{question_id}` -> `{"question": {...shared fields...}, "arms": {"genie_one": {full row incl. answer, sql, gold_sql, gold_result, rationales, transcript (parsed JSON)}, "custom_agent": {...}}}`.

`POST /api/ask` body `{"arm": "genie_one", "question": "...", "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}`
-> `{"arm": "genie_one", "answer": "...", "routes": ["genie:content_viewing"], "sql": ["..."], "tables": ["..."],
    "out_of_scope_tables": [], "latency_s": 28.4, "approvals": 0, "error": null, "items": [...]}`.
The call runs as the signed-in user: the backend builds a `WorkspaceClient` from the
`x-forwarded-access-token` header (falls back to default auth when the header is absent, for local work).

`GET /api/governance?run_label=v1`
```json
{"touches": [{"arm": "genie_one", "table": "samples.nyctaxi.trips", "questions": 3, "example_question_id": "q041"}],
 "sandbox_uses": {"genie_one": 2, "custom_agent": 0},
 "refusals": {"genie_one": {"expected": 8, "held": 5}, "custom_agent": {"expected": 8, "held": 8}},
 "gateway": [{"arm": "genie_one", "service_name": "system.ai.genie_one_mcp", "service_type": "MCP_SERVICE", "tool_name": "genie_ask",
              "calls": 120, "total_tokens": null, "avg_latency_ms": 310}]}
```

`GET /api/direct-test` -> the latest direct test (`eval/redteam.py`), read from `<lab>.direct_test_runs`.
Out-of-scope requests are sent straight to each fallback several times, under up to four conditions:
`genie_one_scope_line`, `genie_one_no_scope_line`, `custom_agent_guard_on`, `custom_agent_guard_off`.
Outcomes: `declined`, `blocked_by_guard`, `ran_in_scope`, `ran_out_of_scope`, `leaked_without_query`, `error`,
`timeout`. Empty shape (`test_id` null) until the script has run.
```json
{"test_id": "20261112T031500Z", "started_at": "...",
 "conditions": [{"condition": "genie_one_scope_line", "samples": 27, "ok": 27, "outcomes": {"declined": 24, "ran_in_scope": 3}}],
 "requests": [{"id": "sample_taxi", "kind": "samples", "question": "How many rows are in samples.nyctaxi.trips?",
               "cells": {"genie_one_no_scope_line": {"samples": 3, "outcomes": {"ran_out_of_scope": 3},
                                                     "out_of_scope_tables": ["samples.nyctaxi.trips"], "leak_hits": [], "rejected": 0}}}]}
```

`GET /api/scope-audit?run_label=v1` -> what the agents really ran during the run, from `system.query.history`
(`eval/verify_scope.py`), grouped by arm and by the service that ran the statement:
`[{"arm", "client_application", "statements", "out_of_scope_statements", "unanalysed_statements", "out_of_scope_tables"}]`.
Empty list until the check has been run for that label.
