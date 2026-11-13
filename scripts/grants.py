"""Give the lab's two apps exactly the Unity Catalog access they need.

  python scripts/grants.py agent   # fallback agent: read in-scope schemas, write traces
  python scripts/grants.py ui      # lab UI: read the lab schema
  python scripts/grants.py ablation  # guard-off build of the fallback agent: write traces, no data access

The fallback agent normally runs SQL as the calling user. Its own grants cover the case where no
user token is forwarded, and they stop at the in-scope schemas: nothing on the off-limits schema.
"""

import json
import sys

from labconfig import cli, load_config, load_state, only_tables, save_state, schema, sql, tables_in_scope

APPS = {"agent": "hoshi-fallback-agent", "ui": "hoshi-fallback-lab", "ablation": "hoshi-fallback-agent-noguard"}
TRACE_TABLES = ("mlflow_experiment_trace_otel_spans", "mlflow_experiment_trace_otel_logs")


def require_trace_tables(cfg: dict, lab: str):
    names = ", ".join(f"'{t}'" for t in TRACE_TABLES)
    found = sql(
        f"SELECT table_name FROM {cfg['workspace']['catalog']}.information_schema.tables "
        f"WHERE table_schema = '{lab.split('.')[1]}' AND table_name IN ({names})",
        cfg,
    )
    missing = sorted(set(TRACE_TABLES) - {row["table_name"] for row in found})
    if missing:
        raise SystemExit(
            f"Missing trace tables in {lab}: {', '.join(missing)}. Run make tracing first, then make agent."
        )


def main():
    which = sys.argv[1]
    cfg = load_config()
    catalog, scope = cfg["workspace"]["catalog"], cfg["scope"]
    app = json.loads(cli("apps", "get", APPS[which], "-o", "json", profile=cfg["workspace"]["profile"]))
    sp, lab = app["service_principal_client_id"], schema(cfg, "lab")
    if which in ("agent", "ablation"):
        require_trace_tables(cfg, lab)
    sql(f"GRANT USE CATALOG ON CATALOG {catalog} TO `{sp}`", cfg)

    if which in ("agent", "ablation"):
        # The guard-off build gets no data access of its own. It only runs SQL as the calling user.
        fallback_domains = sorted({*scope["fallback"], *scope["join_only"]}) if which == "agent" else []
        if fallback_domains and only_tables(cfg) is not None:
            # With a table list the app reads the listed tables only, not the whole schema.
            for domain in fallback_domains:
                sql(f"GRANT USE SCHEMA ON SCHEMA {schema(cfg, domain)} TO `{sp}`", cfg)
            listed = sql(
                f"SELECT table_schema, table_name FROM {catalog}.information_schema.tables "
                f"WHERE {tables_in_scope(cfg, fallback_domains)}",
                cfg,
            )
            for row in listed:
                sql(f"GRANT SELECT ON TABLE {catalog}.{row['table_schema']}.{row['table_name']} TO `{sp}`", cfg)
            print(
                f"scope.only_tables is set: SELECT granted on {len(listed)} tables. A SELECT grant on a whole "
                "schema from an earlier run stays until you revoke it: REVOKE SELECT ON SCHEMA <schema> FROM `"
                f"{sp}`"
            )
        else:
            for domain in fallback_domains:
                sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {schema(cfg, domain)} TO `{sp}`", cfg)
        sql(f"GRANT USE SCHEMA ON SCHEMA {lab} TO `{sp}`", cfg)
        for table in TRACE_TABLES:
            sql(f"GRANT MODIFY, SELECT ON TABLE {lab}.{table} TO `{sp}`", cfg)
        if which == "agent":
            save_state(fallback_app=app["name"], fallback_app_url=app["url"], fallback_app_sp=sp)
    else:
        # The UI flags tables outside the agreed scope. It cannot list the data schemas itself
        # (it has no access to them), so the in-scope table list is copied into the lab schema.
        where = tables_in_scope(
            cfg,
            [*scope["fallback"], *scope["join_only"]],
            always=[d for ds in scope["genie_agents"].values() for d in ds],
        )
        sql(
            f"""CREATE OR REPLACE TABLE {lab}.scope_tables COMMENT 'Tables the lab agents may use' AS
                SELECT table_catalog, table_schema, table_name FROM {catalog}.information_schema.tables
                WHERE {where}""",
            cfg,
        )
        sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {lab} TO `{sp}`", cfg)
        save_state(ui_app=app["name"], ui_app_url=app["url"], ui_app_sp=sp)
    print(f"{which}: grants in place for {app['name']} ({sp})")
    if which == "ui" and "supervisors" in load_state():
        print("The UI calls the supervisors as the signed-in user, so no endpoint grant is needed for the app itself.")


main()
