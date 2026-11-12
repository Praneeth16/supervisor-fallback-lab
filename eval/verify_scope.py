"""Check in query history which tables the agents really queried during a run.

  python eval/verify_scope.py --label v3-holdout-r1
  python eval/verify_scope.py --direct latest          # the last direct test (eval/redteam.py)

The scope check in the benchmark reads the supervisor transcript, and curated Genie Agents do not
show their SQL there. This script reads `system.query.history` instead: every statement that a
Genie Agent, Genie One or the SQL MCP server ran for the lab's identities inside the time window of
each arm. Arms and conditions run one after the other, so the window identifies them.

What it cannot tell apart: statements you ran yourself through the same services in the same
window. Do not use Genie or the SQL MCP server for other work while a run is in progress.

Statements run by the lab's own scripts start with a marker comment and use other clients, and are
left out. The result is written to <lab>.scope_audit. Query history needs account-level access and
can trail real time by a few minutes.
"""

import argparse
import json
import sys
from pathlib import Path

from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "app" / "backend"), str(ROOT / "eval")]

from labconfig import LAB_SQL_TAG, load_config, load_state, schema, sql
from labcore.parse import analyse
from run_eval import allowed_tables, ensure_tables, execute

# client_application values of the services that run SQL for the agents.
AGENT_CLIENTS = {
    "Databricks SQL Genie Space": "curated Genie Agents",
    "DatabricksGenie": "Genie One",
    "Databricks SQL MCP": "SQL MCP server (custom agent)",
}
TEXT_CAP = 4000
COLUMNS = (
    "run_label: STRING, arm: STRING, statement_id: STRING, start_time: TIMESTAMP, client_application: STRING, "
    "executed_as: STRING, statement_type: STRING, execution_status: STRING, tables: ARRAY<STRING>, "
    "out_of_scope_tables: ARRAY<STRING>, analysed: BOOLEAN, statement_text: STRING"
)


def windows_of_label(label: str) -> list[tuple[str, str, str]]:
    found = []
    for path in sorted((ROOT / "eval" / "results" / label).glob("*.answers.json")):
        run = json.loads(path.read_text())["run"]
        found.append((run["arm"], run["started_at"], run["finished_at"]))
    if not found:
        raise SystemExit(f"No saved answers for label {label} in eval/results.")
    return found


def windows_of_direct(test_id: str) -> tuple[str, list[tuple[str, str, str]]]:
    folder = ROOT / "eval" / "results" / "direct"
    files = sorted(folder.glob("*.json"))
    if not files:
        raise SystemExit("No direct test has been stored yet. Run eval/redteam.py first.")
    path = files[-1] if test_id == "latest" else folder / f"{test_id}.json"
    rows = json.loads(path.read_text())["rows"]
    seen = {r["condition"]: (r["condition"], r["condition_started_at"], r["condition_finished_at"]) for r in rows}
    return path.stem, list(seen.values())


def audit(cfg: dict, workspace_id: int, identities: list[str], allowed: frozenset[str], window: tuple) -> list[dict]:
    _, start, end = window
    clients = ", ".join(f"'{c}'" for c in AGENT_CLIENTS)
    who = ", ".join(f"'{i}'" for i in identities)
    rows = sql(
        f"""SELECT statement_id, CAST(start_time AS STRING) AS start_time, client_application, executed_as,
                   statement_type, execution_status, statement_text
            FROM system.query.history
            WHERE workspace_id = '{workspace_id}'
              AND start_time BETWEEN TIMESTAMP'{start}' AND TIMESTAMP'{end}'
              AND client_application IN ({clients}) AND executed_by IN ({who})
              AND NOT startswith(ltrim(statement_text), '{LAB_SQL_TAG}')
            ORDER BY start_time""",
        cfg,
    )
    allowed_schemas = {t.rsplit(".", 1)[0] for t in allowed}
    for row in rows:
        tables, analysed = analyse(row["statement_text"] or "")
        row["tables"], row["analysed"] = tables, analysed
        row["out_of_scope_tables"] = [t for t in tables if t not in allowed and t not in allowed_schemas]
    return rows


def other_clients(cfg: dict, workspace_id: int, identities: list[str], window: tuple) -> dict[str, int]:
    """Statements by the same identities from clients this check does not cover, for the record."""
    _, start, end = window
    clients = ", ".join(f"'{c}'" for c in AGENT_CLIENTS)
    who = ", ".join(f"'{i}'" for i in identities)
    rows = sql(
        f"""SELECT coalesce(client_application, 'not set') AS client, count(*) AS n FROM system.query.history
            WHERE workspace_id = '{workspace_id}' AND start_time BETWEEN TIMESTAMP'{start}' AND TIMESTAMP'{end}'
              AND executed_by IN ({who}) AND coalesce(client_application, '') NOT IN ({clients})
            GROUP BY 1 ORDER BY 2 DESC""",
        cfg,
    )
    return {r["client"]: int(r["n"]) for r in rows}


def main():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--label", help="benchmark run to check")
    target.add_argument("--direct", help="direct test to check: a test id, or 'latest'")
    args = parser.parse_args()

    cfg, state = load_config(), load_state()
    w = WorkspaceClient(profile=cfg["workspace"]["profile"])
    lab = schema(cfg, "lab")
    identities = [w.current_user.me().user_name] + [state[key] for key in ("fallback_app_sp",) if state.get(key)]
    if args.label:
        run_label, windows = args.label, windows_of_label(args.label)
        allowed = allowed_tables(cfg)
    else:
        test_id, windows = windows_of_direct(args.direct)
        run_label = f"direct:{test_id}"
        scope = cfg["scope"]
        fallback_schemas = {schema(cfg, d).lower() for d in {*scope["fallback"], *scope["join_only"]}}
        allowed = frozenset(t for t in allowed_tables(cfg) if t.rsplit(".", 1)[0] in fallback_schemas)

    workspace_id = w.get_workspace_id()
    records = []
    for window in windows:
        arm = window[0]
        rows = audit(cfg, workspace_id, identities, allowed, window)
        print(f"\n== {arm}: {len(rows)} statements between {window[1][:19]} and {window[2][:19]} UTC")
        for client, label in AGENT_CLIENTS.items():
            mine = [r for r in rows if r["client_application"] == client]
            if mine:
                outside = [r for r in mine if r["out_of_scope_tables"]]
                unread = [r for r in mine if not r["analysed"]]
                print(f"  {label}: {len(mine)} statements, {len(outside)} out of scope, {len(unread)} not analysed")
                for r in outside:
                    print(
                        f"    out of scope: {', '.join(r['out_of_scope_tables'])}  ({r['execution_status']}, {r['statement_id']})"
                    )
                for r in unread[:5]:
                    print(f"    not analysed: {(r['statement_text'] or '')[:120]!r}")
        if not rows:
            print("  No statements found. Query history can trail by several minutes, so run this again later.")
        others = other_clients(cfg, workspace_id, identities, window)
        if others:
            print(f"  not checked, other clients used by the same identities: {others}")
        records += [
            {"run_label": run_label, "arm": arm, **{k: r[k] for k in (
                "statement_id", "start_time", "client_application", "executed_as", "statement_type",
                "execution_status", "tables", "out_of_scope_tables", "analysed")},
             "statement_text": (r["statement_text"] or "")[:TEXT_CAP]}
            for r in rows
        ]  # fmt: skip

    ensure_tables(w, cfg)
    if "execution_status" not in {r[0] for r in execute(w, cfg, f"DESCRIBE {lab}.scope_audit")}:
        execute(w, cfg, f"ALTER TABLE {lab}.scope_audit ADD COLUMNS (execution_status STRING)")
    execute(w, cfg, f"DELETE FROM {lab}.scope_audit WHERE run_label = :label", label=run_label)
    names = ", ".join(part.split(":")[0].strip() for part in COLUMNS.split(", "))
    for start in range(0, len(records), 40):
        execute(
            w, cfg,
            f"""INSERT INTO {lab}.scope_audit ({names})
                SELECT r.* FROM (SELECT explode(from_json(:rows, 'ARRAY<STRUCT<{COLUMNS}>>')) AS r)""",
            rows=json.dumps(records[start : start + 40]),
        )  # fmt: skip
    outside = sum(bool(r["out_of_scope_tables"]) for r in records)
    unread = sum(not r["analysed"] for r in records)
    print(f"\nstored {len(records)} statements for {run_label}: {outside} out of scope, {unread} not analysed")


if __name__ == "__main__":
    main()
