"""Save what the supervisor traces say each agent ran, one small file per arm.

  python eval/export_traces.py --label v3-holdout-r1

Every benchmark turn is traced by the supervisor, and the trace id is saved with the answer. The
trace holds one span for each tool call. The span of a curated Genie Agent carries the SQL that
agent ran (`sql_query`), which the supervisor's reply does not show. This script reads the traces
of a run and keeps, for every turn, the tools that were called and the SQL of each, checked against
the scope. The full traces stay in MLflow. They are too large to keep in the repo.

Output: eval/results/<label>/<arm>.trace-summary.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "app" / "backend"), str(ROOT / "eval")]

RESULTS = ROOT / "eval" / "results"
TRIES = 4


def sql_that_ran(value) -> list[str]:
    """SQL in a span output. For the custom agent only the statements under its footer count as run."""
    from labcore.parse import _AGENT_FOOTER, _split_agent_output, _sql_in

    if isinstance(value, str):
        return _split_agent_output(value)[0]
    if isinstance(value, dict | list):
        if json.dumps(_AGENT_FOOTER)[1:-1] not in json.dumps(value):
            return _sql_in(value)
        inner = value.values() if isinstance(value, dict) else value
        return [s for v in inner for s in sql_that_ran(v)]
    return []


def tool_calls(trace, allowed: frozenset[str]) -> list[dict]:
    """One entry for each tool span: its name, the SQL it reports, and tables outside the scope."""
    from labcore.parse import analyse, route_of

    allowed_schemas = {t.rsplit(".", 1)[0] for t in allowed}
    calls = []
    for span in trace.data.spans:
        if span.span_type != "TOOL":
            continue
        attributes = span.attributes or {}
        statements = [attributes["sql_query"]] if attributes.get("sql_query") else []
        statements += [s for s in sql_that_ran(span.outputs) if s not in statements]
        tables, unread = set(), 0
        for statement in statements:
            found, analysed = analyse(statement)
            tables |= set(found)
            unread += not analysed
        calls.append({
            "tool": span.name, "route": route_of(span.name), "genie_space_id": attributes.get("genie_space_id"),
            "conversation_id": attributes.get("conversation_id"), "sql": statements, "tables": sorted(tables),
            "out_of_scope": sorted(t for t in tables if t not in allowed and t not in allowed_schemas),
            "sql_not_analysed": unread,
        })  # fmt: skip
    return calls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    import mlflow
    from labconfig import load_config
    from run_eval import allowed_tables

    cfg = load_config()
    mlflow.set_tracking_uri("databricks")
    allowed = allowed_tables(cfg)
    for path in sorted((RESULTS / args.label).glob("*.answers.json")):
        saved = json.loads(path.read_text())
        arm, turns, missing = saved["run"]["arm"], {}, 0
        for row in saved["rows"]:
            calls = []
            for trace_id in row.get("trace_ids") or []:
                for attempt in range(TRIES):
                    try:
                        calls.append({"trace_id": trace_id, "tools": tool_calls(mlflow.get_trace(trace_id), allowed)})
                        break
                    except Exception as e:  # noqa: BLE001  the CLI token lookup fails now and then
                        if attempt == TRIES - 1:
                            missing += 1
                            calls.append({"trace_id": trace_id, "error": str(e)[:200]})
                        time.sleep(3 * (attempt + 1))
            turns[row["question_id"]] = calls
        out = path.with_name(f"{arm}.trace-summary.json")
        out.write_text(json.dumps({"label": args.label, "arm": arm, "turns": turns}, indent=1))
        tools = [t for calls in turns.values() for c in calls for t in c.get("tools", [])]
        by_route: dict[str, list[dict]] = {}
        for t in tools:
            by_route.setdefault(t["route"], []).append(t)
        traced = sum(bool(c) for c in turns.values())
        print(f"{args.label} / {arm}: {traced} of {len(turns)} turns traced, {missing} traces could not be read")
        for route, items in sorted(by_route.items()):
            print(
                f"  {route}: {len(items)} calls, {sum(len(t['sql']) for t in items)} statements, "
                f"{sum(bool(t['out_of_scope']) for t in items)} calls out of scope, "
                f"{sum(t['sql_not_analysed'] for t in items)} statements not analysed"
            )


if __name__ == "__main__":
    main()
