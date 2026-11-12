"""Create or update the Hoshi Stream licensing and ad sales dashboard, then publish it.

Reads the definition in dashboard.lvdash.json, fills the {catalog} and {prefix} placeholders from
lab.yaml, and writes the result to the dashboard named in state.json (or creates one). It is
published without embedded credentials: every viewer queries as themselves.

Usage: deploy_dashboard.py
"""

import json
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from labconfig import api, load_config, load_state, save_state

DEFINITION = ROOT / "data_model" / "dashboard.lvdash.json"
DISPLAY_NAME = "Hoshi Stream: Licensing and Ad Sales"


def render_definition(cfg: dict) -> str:
    ws = cfg["workspace"]
    text = DEFINITION.read_text().replace("{catalog}", ws["catalog"]).replace("{prefix}", ws["schema_prefix"])
    return json.dumps(json.loads(text))


def main() -> None:
    cfg = load_config()
    state = load_state()
    serialized = render_definition(cfg)
    warehouse_id = cfg["workspace"]["warehouse_id"]
    host = cfg["workspace"]["host"].rstrip("/")
    existing = state.get("dashboard", {}).get("id")

    if existing:
        dash = api(
            "patch",
            f"/api/2.0/lakeview/dashboards/{existing}",
            cfg,
            {"display_name": DISPLAY_NAME, "serialized_dashboard": serialized},
        )
    else:
        parent = str(PurePosixPath(state["experiment_name"]).parent)
        dash = api(
            "post",
            "/api/2.0/lakeview/dashboards",
            cfg,
            {
                "display_name": DISPLAY_NAME,
                "warehouse_id": warehouse_id,
                "parent_path": parent,
                "serialized_dashboard": serialized,
            },
        )

    dashboard_id = dash["dashboard_id"]
    api(
        "post",
        f"/api/2.0/lakeview/dashboards/{dashboard_id}/published",
        cfg,
        # Viewers query with their own identity, so the dashboard shows each person only what
        # Unity Catalog lets them read. They need access to the warehouse and to the tables.
        {"warehouse_id": warehouse_id, "embed_credentials": False},
    )

    record = {
        "id": dashboard_id,
        "name": DISPLAY_NAME,
        "path": dash["path"],
        "url": f"{host}/sql/dashboardsv3/{dashboard_id}/published",
    }
    save_state(dashboard=record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
