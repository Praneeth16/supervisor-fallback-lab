"""Write app/backend/app.yaml for the lab UI from lab.yaml and state.json."""

import json

import yaml
from labconfig import ROOT, load_config, load_state, schema


def main():
    cfg, state = load_config(), load_state()
    catalog, lab_schema = schema(cfg, "lab").split(".")
    env = {
        "LAB_CATALOG": catalog,
        "LAB_SCHEMA": lab_schema,
        "SUPERVISOR_A_ENDPOINT": state["supervisors"]["genie_one"]["endpoint"],
        "SUPERVISOR_B_ENDPOINT": state["supervisors"]["custom_agent"]["endpoint"],
        "SUPERVISOR_A_EXPERIMENT": str(state["supervisors"]["genie_one"].get("experiment_id") or ""),
        "SUPERVISOR_B_EXPERIMENT": str(state["supervisors"]["custom_agent"].get("experiment_id") or ""),
        "LAB_BRAND": cfg["brand"],
        "LAB_SCOPE_JSON": json.dumps(cfg["scope"]),
        "LAB_FIXTURES": "0",
    }
    # Optional. How many fallback questions from how many people flag a table for a curated Genie Agent.
    demand = (cfg.get("ui") or {}).get("fallback_demand") or {}
    if demand.get("min_questions"):
        env["LAB_DEMAND_MIN_QUESTIONS"] = str(demand["min_questions"])
    if demand.get("min_people"):
        env["LAB_DEMAND_MIN_PEOPLE"] = str(demand["min_people"])
    app = {
        "command": ["uv", "run", "start-app"],
        "env": [{"name": "DATABRICKS_WAREHOUSE_ID", "valueFrom": "sql-warehouse"}]
        + [{"name": k, "value": v} for k, v in env.items()],
    }
    (ROOT / "app" / "backend" / "app.yaml").write_text(yaml.safe_dump(app, sort_keys=False, width=1000))
    print("wrote app/backend/app.yaml")


main()
