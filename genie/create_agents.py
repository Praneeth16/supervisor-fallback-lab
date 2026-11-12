"""Create or update the two curated Genie Agents through the Genie Workbench app.

Each agent is described in a short YAML file in this folder. This script turns it into the
Workbench's `serialized_space` (version 2), validates it with the Workbench, creates the agent
through the Workbench's create endpoint, and runs the Workbench IQ scan on the result.

  python genie/create_agents.py                 # both agents
  python genie/create_agents.py content_viewing # one agent

Calls to the Workbench app need a bearer token. It is fetched from the Databricks CLI for each
run, held in memory only, and never printed or written to disk.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from labconfig import api, load_config, load_state, placeholders, save_state, sql

HERE = Path(__file__).resolve().parent


def uid(*parts: str) -> str:
    """Stable 32-hex id, so re-running the script keeps the same ids."""
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def bearer(profile: str) -> dict:
    out = subprocess.run(
        ["databricks", "auth", "token", "--profile", profile], capture_output=True, text=True, check=True
    )
    return {"Authorization": f"Bearer {json.loads(out.stdout)['access_token']}"}


def lines(text: str) -> list[str]:
    return [line + "\n" for line in text.strip().splitlines()]


def build(spec: dict, cfg: dict) -> dict:
    catalog = cfg["workspace"]["catalog"]
    names = placeholders(cfg)
    key = spec["key"]

    def fq(ref: str) -> str:  # "subscriber.subscription" -> catalog.<prefix>subscriber.subscription
        domain, table = ref.split(".")
        return f"{names[domain]}.{table}"

    tables = []
    for ref in spec["tables"]:
        domain, table = ref.split(".")
        schema_name = names[domain].split(".")[1]
        comment = sql(
            f"SELECT comment FROM {catalog}.information_schema.tables "
            f"WHERE table_schema = '{schema_name}' AND table_name = '{table}'",
            cfg,
        )[0]["comment"]
        columns = sql(
            f"SELECT column_name, comment FROM {catalog}.information_schema.columns "
            f"WHERE table_schema = '{schema_name}' AND table_name = '{table}' ORDER BY column_name",
            cfg,
        )
        matched = set(spec.get("value_columns", {}).get(ref, []))
        hidden = set(spec.get("hidden_columns", {}).get(ref, []))
        tables.append(
            {
                "identifier": fq(ref),
                "description": [comment or ""],
                "column_configs": [
                    {
                        "column_name": c["column_name"],
                        "description": [c["comment"] or ""],
                        "exclude": c["column_name"] in hidden,
                        "enable_format_assistance": c["column_name"] not in hidden,
                        "enable_entity_matching": c["column_name"] in matched,
                    }
                    for c in columns
                ],
            }
        )

    def snippets(kind: str) -> list[dict]:
        return sorted(
            (
                {
                    "id": uid(key, kind, s["name"]),
                    "display_name": s["name"],
                    "sql": [s["sql"].format(**names)],
                    **({"synonyms": s["synonyms"]} if s.get("synonyms") else {}),
                    **({"instruction": [s["when"]]} if s.get("when") else {}),
                }
                for s in spec.get(kind, [])
            ),
            key=lambda s: s["id"],
        )

    joins = []
    for j in spec.get("joins", []):
        left, right = j["left"].split(".")[1], j["right"].split(".")[1]
        left_col, right_col = j["keys"]
        joins.append(
            {
                "id": uid(key, "join", j["left"], j["right"]),
                "left": {"identifier": fq(j["left"]), "alias": left},
                "right": {"identifier": fq(j["right"]), "alias": right},
                "sql": [
                    f"`{left}`.`{left_col}` = `{right}`.`{right_col}`",
                    f"--rt=FROM_RELATIONSHIP_TYPE_{j.get('type', 'MANY_TO_ONE')}--",
                ],
            }
        )

    return {
        "version": 2,
        "config": {
            "sample_questions": sorted(
                ({"id": uid(key, "sample", q), "question": [q]} for q in spec["sample_questions"]),
                key=lambda q: q["id"],
            )
        },
        "data_sources": {"tables": sorted(tables, key=lambda t: t["identifier"])},
        "instructions": {
            "text_instructions": [{"id": uid(key, "text"), "content": lines(spec["instructions"])}],
            "example_question_sqls": sorted(
                (
                    {
                        "id": uid(key, "example", e["question"]),
                        "question": [e["question"]],
                        "sql": lines(e["sql"].format(**names)),
                    }
                    for e in spec.get("examples", [])
                ),
                key=lambda e: e["id"],
            ),
            "join_specs": sorted(joins, key=lambda j: j["id"]),
            "sql_snippets": {k: snippets(k) for k in ("filters", "expressions", "measures")},
        },
        "benchmarks": {
            "questions": sorted(
                (
                    {
                        "id": uid(key, "benchmark", b["question"]),
                        "question": [b["question"]],
                        "answer": [{"format": "SQL", "content": lines(b["sql"].format(**names))}],
                    }
                    for b in spec.get("benchmarks", [])
                ),
                key=lambda b: b["id"],
            )
        },
    }


def publish(key: str, cfg: dict, state: dict) -> dict:
    spec = yaml.safe_load((HERE / f"{key}.yaml").read_text())
    space = build(spec, cfg)
    (HERE / "rendered").mkdir(exist_ok=True)
    (HERE / "rendered" / f"{key}.json").write_text(json.dumps(space, indent=2) + "\n")

    workbench = state["workbench_url"]
    headers = bearer(cfg["workspace"]["profile"])
    check = requests.post(
        f"{workbench}/api/create/validate", headers=headers, json={"serialized_space": space}, timeout=120
    )
    check.raise_for_status()
    verdict = check.json()
    for warning in verdict.get("warnings", []):
        print(f"  warning: {warning}")
    if not verdict.get("valid"):
        raise SystemExit(f"{key}: Workbench validation failed: {verdict.get('errors')}")

    existing = state.get("genie_spaces", {}).get(key)
    if existing:
        api(
            "patch",
            f"/api/2.0/genie/spaces/{existing}",
            cfg,
            {"title": spec["display_name"], "description": spec["description"], "serialized_space": json.dumps(space)},
        )
        space_id = existing
    else:
        user = api("get", "/api/2.0/preview/scim/v2/Me", cfg)["userName"]
        created = requests.post(
            f"{workbench}/api/create",
            headers=headers,
            json={
                "display_name": spec["display_name"],
                "description": spec["description"],
                "parent_path": f"/Users/{user}/",
                "serialized_space": space,
            },
            timeout=300,
        )
        if created.status_code != 200:
            raise SystemExit(f"{key}: Workbench create failed ({created.status_code}): {created.text[:500]}")
        space_id = created.json()["space_id"]

    scan = requests.post(f"{workbench}/api/spaces/{space_id}/scan", headers=headers, timeout=300)
    result = scan.json() if scan.status_code == 200 else {"error": f"{scan.status_code}: {scan.text[:300]}"}
    failed = [c["label"] for c in result.get("checks", []) if not c.get("passed")]
    print(
        f"{key}: space {space_id}, {len(space['data_sources']['tables'])} tables, "
        f"IQ scan {result.get('score')}/{result.get('total')} ({result.get('maturity')}); not passed: {failed or 'none'}"
    )
    return {"id": space_id, "scan": {k: result.get(k) for k in ("score", "total", "maturity", "error") if k in result}}


def main():
    cfg, state = load_config(), load_state()
    spaces, scans = state.get("genie_spaces", {}), state.get("genie_scans", {})
    for key in sys.argv[1:] or list(cfg["scope"]["genie_agents"]):
        out = publish(key, cfg, state | {"genie_spaces": spaces})
        spaces[key], scans[key] = out["id"], out["scan"]
        save_state(genie_spaces=spaces, genie_scans=scans)


main()
