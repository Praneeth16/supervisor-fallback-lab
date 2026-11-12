"""Settings from environment variables, and the public /api/config payload."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = BACKEND_DIR / "fixtures"
STATIC_DIR = BACKEND_DIR / "static"

ARMS = ("genie_one", "custom_agent")
CATEGORIES = (
    "curated_subscriber",
    "curated_content",
    "long_tail",
    "cross_domain",
    "must_refuse",
    "ambiguous",
    # hard question set (eval/benchmark_hard.yaml)
    "routing_trap",
    "hard_sql",
    "data_trap",
    "multi_hop",
    "unanswerable",
    "adversarial",
)
ARM_TEXT = {
    "genie_one": {
        "label": "Supervisor A: Genie Agents + Genie One",
        "fallback": "Genie One managed MCP, scope set by instructions and skills",
    },
    "custom_agent": {
        "label": "Supervisor B: Genie Agents + custom agent",
        "fallback": "Custom text-to-SQL agent, scope enforced in code",
    },
}
DEFAULT_SCOPE = {
    "genie_agents": {"subscribers_revenue": ["subscriber", "billing"], "content_viewing": ["content", "distribution"]},
    "fallback": ["rights", "sales", "partner"],
    "join_only": ["subscriber", "billing", "content", "distribution"],
    "off_limits": ["talent"],
}
DEFAULT_BRAND = "Hoshi Stream"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class Settings:
    fixtures: bool
    catalog: str
    schema: str
    warehouse_id: str
    endpoints: dict[str, str]
    brand: str
    scope: dict
    workspace_host: str | None

    @property
    def schema_prefix(self) -> str:
        """Domain schemas are `<prefix><domain>`; the lab schema is `<prefix>lab`."""
        return self.schema[:-3] if self.schema.endswith("lab") else self.schema

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        catalog = env.get("LAB_CATALOG", "serverless_lakebase_praneeth_catalog")
        schema = env.get("LAB_SCHEMA", "hoshi_lab")
        for name, value in (("LAB_CATALOG", catalog), ("LAB_SCHEMA", schema)):
            if not _IDENTIFIER.match(value):
                raise ValueError(f"{name} must be a plain identifier, got {value!r}")
        scope = json.loads(env["LAB_SCOPE_JSON"]) if env.get("LAB_SCOPE_JSON") else DEFAULT_SCOPE
        return cls(
            fixtures=env.get("LAB_FIXTURES", "0") == "1",
            catalog=catalog,
            schema=schema,
            warehouse_id=env.get("DATABRICKS_WAREHOUSE_ID", ""),
            endpoints={
                "genie_one": env.get("SUPERVISOR_A_ENDPOINT", "supervisor-a-endpoint"),
                "custom_agent": env.get("SUPERVISOR_B_ENDPOINT", "supervisor-b-endpoint"),
            },
            brand=env.get("LAB_BRAND", DEFAULT_BRAND),
            scope=scope,
            workspace_host=env.get("DATABRICKS_HOST") or None,
        )


def config_payload(settings: Settings) -> dict:
    return {
        "brand": settings.brand,
        "arms": [
            {
                "key": arm,
                "label": ARM_TEXT[arm]["label"],
                "fallback": ARM_TEXT[arm]["fallback"],
                "endpoint": settings.endpoints[arm],
            }
            for arm in ARMS
        ],
        "scope": settings.scope,
        "categories": list(CATEGORIES),
        "workspace_host": settings.workspace_host,
    }
