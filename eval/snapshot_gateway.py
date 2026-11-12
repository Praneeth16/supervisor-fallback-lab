"""Copy the Unity Gateway usage of one evaluation run into the lab schema.

  python eval/snapshot_gateway.py --label v1

`system.ai_gateway.usage` records every model and MCP call that went through Unity Gateway. It
needs account-level access and trails real time by up to an hour. This script, run by someone who
can read it, copies the rows that fall inside each arm's run window into <lab>.gateway_usage, which
the lab UI can read. Arms run one after the other, so a time window identifies the arm.

Only calls made by the lab's identities are copied: the person who ran the benchmark and the
fallback agent's service principal. Calls that Genie One itself makes to other MCP services, such as
the connectors of the person asking, are copied too (source GENIE_ONE), whatever the service. If the usage table has no rows for the run yet, the snapshot
that is already stored is kept.

What the gateway does not show, so it is missing here:
  - the supervisor's own model calls (their tokens come from the supervisor traces instead, see
    supervisor_tokens in <lab>.eval_results)
  - the models inside Genie One and inside the curated Genie Agents. Calls to Genie One are
    counted, but no tokens are reported for them
  - the judge model calls of the evaluation
"""

import argparse
import sys
from pathlib import Path

from databricks.sdk import WorkspaceClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from labconfig import load_config, load_state, schema, sql

SERVICES = ("system.ai.genie_one_mcp", "system.ai.dbsql")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    cfg, state = load_config(), load_state()
    lab = schema(cfg, "lab")
    w = WorkspaceClient(profile=cfg["workspace"]["profile"])
    services = ", ".join(f"'{s}'" for s in (*SERVICES, cfg["models"]["agent"]))
    requesters = ", ".join(f"'{r}'" for r in (w.current_user.me().user_name, state.get("fallback_app_sp")) if r)
    label = args.label.replace("'", "")
    # A label has one window per arm, however many times its answers were graded.
    source = f"""
        FROM system.ai_gateway.usage u
        JOIN (SELECT DISTINCT run_label, arm, started_at, finished_at FROM {lab}.eval_runs
              WHERE run_label = '{label}') r
          ON u.event_time BETWEEN r.started_at AND r.finished_at
        WHERE u.workspace_id = '{w.get_workspace_id()}' AND u.requester IN ({requesters})
          AND (u.service_name IN ({services}) OR u.invocation_metadata.source = 'GENIE_ONE')"""

    found = int(sql(f"SELECT count(*) AS n {source}", cfg)[0]["n"])
    stored = int(sql(f"SELECT count(*) AS n FROM {lab}.gateway_usage WHERE run_label = '{label}'", cfg)[0]["n"])
    if found == 0:
        print(f"No gateway usage found for {label} yet. Kept the stored snapshot ({stored} rows). Try again later.")
        return
    sql(f"DELETE FROM {lab}.gateway_usage WHERE run_label = '{label}'", cfg)
    sql(
        f"""INSERT INTO {lab}.gateway_usage
            SELECT r.run_label, r.arm, u.event_time, u.service_name, u.service_type, u.mcp_metadata.tool_name,
                   u.requester, u.requester_type, u.invocation_metadata.source,
                   try_cast(u.input_tokens AS BIGINT), try_cast(u.output_tokens AS BIGINT),
                   try_cast(u.total_tokens AS BIGINT), try_cast(u.latency_ms AS BIGINT),
                   try_cast(u.status_code AS INT)
            {source}""",
        cfg,
    )
    print(f"{label}: stored {found} rows (was {stored})")
    for row in sql(
        f"""SELECT arm, service_name, coalesce(tool_name, '') AS tool, count(*) AS calls, sum(total_tokens) AS tokens
            FROM {lab}.gateway_usage WHERE run_label = '{label}' GROUP BY ALL ORDER BY arm, calls DESC""",
        cfg,
    ):
        print(" ", row)


main()
