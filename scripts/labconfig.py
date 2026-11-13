"""Shared helpers for the lab scripts: config, generated state, and SQL through the Databricks CLI.

Scripts never handle tokens. Workspace calls go through the `databricks` CLI or the SDK, both of
which authenticate with the profile named in lab.yaml.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"
CLI_TRIES = 5


def load_config() -> dict:
    cfg = yaml.safe_load((ROOT / "lab.yaml").read_text())
    # The lab always talks to the workspace named in lab.yaml, whatever the shell has set.
    os.environ["DATABRICKS_CONFIG_PROFILE"] = cfg["workspace"]["profile"]
    return cfg


def schema(cfg: dict, domain: str) -> str:
    ws = cfg["workspace"]
    return f"{ws['catalog']}.{ws['schema_prefix']}{domain}"


def only_tables(cfg: dict) -> frozenset[str] | None:
    """scope.only_tables as lower-case schema.table names, or None when the key is not set.

    Entries may be written schema.table or catalog.schema.table. Every entry has to sit in a schema
    listed under scope.fallback or scope.join_only, because a table anywhere else is never in scope.
    """
    listed = cfg["scope"].get("only_tables")
    if not listed:
        return None
    catalog = cfg["workspace"]["catalog"].lower()
    scope = cfg["scope"]
    schemas = {schema(cfg, d).split(".")[1].lower() for d in {*scope["fallback"], *scope["join_only"]}}
    names = set()
    for entry in listed:
        parts = str(entry).strip().strip("`").lower().split(".")
        if len(parts) == 3 and parts[0] == catalog:
            parts = parts[1:]
        if len(parts) != 2:
            raise SystemExit(f"scope.only_tables: write {entry!r} as schema.table or {catalog}.schema.table.")
        if parts[0] not in schemas:
            raise SystemExit(
                f"scope.only_tables: {entry!r} is in schema {parts[0]}, which is not under scope.fallback or scope.join_only."
            )
        names.add(".".join(parts))
    return frozenset(names)


def tables_in_scope(cfg: dict, domains, always=()) -> str:
    """SQL condition on information_schema.tables for the tables of these domains that are in scope.

    Without scope.only_tables this is every table in the schemas of `domains` and `always`. With it,
    a table of `domains` passes only when it is listed. Tables of the `always` domains pass
    unfiltered: these are the schemas of the curated Genie Agents, which the list does not narrow.
    Every script that lists in-scope tables uses this condition, so both fallbacks get the same scope.
    """

    def schema_list(names) -> str:
        return ", ".join(f"'{schema(cfg, d).split('.')[1]}'" for d in sorted(set(names)))

    listed = only_tables(cfg)
    if listed is None:
        return f"table_schema IN ({schema_list([*domains, *always])})"
    quoted = ", ".join(f"'{name}'" for name in sorted(listed))
    narrowed = (
        f"table_schema IN ({schema_list(domains)}) AND lower(concat(table_schema, '.', table_name)) IN ({quoted})"
    )
    if not always:
        return narrowed
    return f"(table_schema IN ({schema_list(always)}) OR ({narrowed}))"


DOMAINS = ["subscriber", "billing", "content", "distribution", "rights", "sales", "partner", "talent", "lab"]


def placeholders(cfg: dict) -> dict:
    """Values for {subscriber}, {rights}, ... and {today} in SQL kept in YAML files."""
    return {d: schema(cfg, d) for d in DOMAINS} | {"today": f"DATE'{cfg['data']['as_of']}'"}


def data_rules(cfg: dict) -> list[str]:
    """Rules about the data that both fallbacks get word for word, so neither knows more than the other."""
    as_of = cfg["data"]["as_of"]
    metric_views = (
        "Names ending in `_metrics` are metric views. Query them with "
        "`SELECT <dimension>, MEASURE(<measure>) FROM <view> GROUP BY <dimension>`; a plain `SELECT *` fails."
    )
    today = (
        f"The data runs through the day before {as_of}. Treat {as_of} as today for relative dates such as "
        f'"last month" or "next 90 days", and write it as DATE\'{as_of}\' instead of current_date().'
    )
    return [
        metric_views,
        "Money is in US dollars unless a currency column says otherwise.",
        today,
        'For "lately" or "recently", cover the last six months and name the main driver over that period.',
        "Join on id columns. Names of titles, films and specials repeat.",
    ]


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(**updates) -> dict:
    state = load_state() | updates
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


def cli(*args: str, profile: str) -> str:
    # When several lab processes run at once, the CLI's token lookup can fail for a moment
    # ("OS keyring unreachable"). That error is retried; every other error is raised at once.
    for attempt in range(CLI_TRIES):
        out = subprocess.run(["databricks", *args, "--profile", profile], capture_output=True, text=True, check=False)
        if out.returncode == 0:
            return out.stdout
        message = out.stderr.strip() or out.stdout.strip()
        if "keyring" not in message or attempt == CLI_TRIES - 1:
            raise RuntimeError(message)
        time.sleep(3 * (attempt + 1))
    raise AssertionError("unreachable")


def api(method: str, path: str, cfg: dict, body: dict | None = None) -> dict:
    args = ["api", method, path]
    if body is not None:
        args += ["--json", json.dumps(body)]
    out = cli(*args, profile=cfg["workspace"]["profile"])
    return json.loads(out) if out.strip() else {}


# Every statement the lab's own scripts run starts with this comment, so the execution-level scope
# check (eval/verify_scope.py) can tell them apart from statements run by the agents.
LAB_SQL_TAG = "/* hoshi-lab-infra */"


def sql(statement: str, cfg: dict) -> list[dict]:
    """Run one SQL statement on the lab warehouse and return rows as dicts."""
    ws = cfg["workspace"]
    out = api(
        "post",
        "/api/2.0/sql/statements",
        cfg,
        {
            "warehouse_id": ws["warehouse_id"],
            "statement": f"{LAB_SQL_TAG} {statement}",
            "wait_timeout": "50s",
            "format": "JSON_ARRAY",
        },
    )
    while out["status"]["state"] in ("PENDING", "RUNNING"):
        out = api("get", f"/api/2.0/sql/statements/{out['statement_id']}", cfg)
    if out["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(out["status"].get("error", {}).get("message", out["status"]["state"]))
    columns = [c["name"] for c in out.get("manifest", {}).get("schema", {}).get("columns", [])]
    return [dict(zip(columns, row)) for row in out.get("result", {}).get("data_array", [])]
