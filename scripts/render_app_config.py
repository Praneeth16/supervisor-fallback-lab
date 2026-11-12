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
        "LAB_BRAND": cfg["brand"],
        "LAB_SCOPE_JSON": json.dumps(cfg["scope"]),
        "LAB_FIXTURES": "0",
    }
    app = {
        "command": ["uv", "run", "start-app"],
        "env": [{"name": "DATABRICKS_WAREHOUSE_ID", "valueFrom": "sql-warehouse"}]
        + [{"name": k, "value": v} for k, v in env.items()],
    }
    (ROOT / "app" / "backend" / "app.yaml").write_text(yaml.safe_dump(app, sort_keys=False, width=1000))
    print("wrote app/backend/app.yaml")


main()
