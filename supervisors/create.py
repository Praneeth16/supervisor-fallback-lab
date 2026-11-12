"""Create or update the two Supervisor Agents of the lab.

Both get the same two Genie Agents and the same routing rules. They differ only in the fallback:
arm `genie_one` gets the managed Genie One MCP plus a scope skill, arm `custom_agent` gets the
custom agent app. Safe to re-run: supervisors are matched by display name, and tools and routing
examples are brought in line with this file without ever leaving the supervisor empty.

Usage: python supervisors/create.py [genie_one|custom_agent]   (default: both)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from labconfig import api, cli, load_config, load_state, save_state, schema

HERE = Path(__file__).resolve().parent
API = "/api/2.1/supervisor-agents"

GENIE_TOOLS = {
    "subscribers_revenue": (
        "Curated Genie Agent for subscribers and revenue: subscriber accounts, plans, subscriptions, sign-ups, "
        "churn events and reasons, offers and redemptions, invoices, payments, payment failures and refunds. "
        "Use it for any question answered from subscriber or billing data alone."
    ),
    "content_viewing": (
        "Curated Genie Agent for content and viewing: titles, series, seasons, episodes, genres, simulcasts, "
        "playback sessions, watch time, completion, devices and platforms, audio and subtitle language. "
        "Use it for any question answered from catalogue or viewing data alone."
    ),
}
FALLBACK_COVERS = (
    "everything else about {brand} data: content licensing and rights, licensors, territories and availability "
    "windows, royalties, advertisers, campaigns, ad orders and impression delivery, acquisition deals and minimum "
    "guarantees, and questions that must join more than one area in a single query."
)
ARMS = {
    "genie_one": {
        "display_name": "hoshi-supervisor-genie-one",
        "description": "Hoshi Stream data assistant: two curated Genie Agents, Genie One as the fallback.",
        "fallback_name": "Genie One (tools `genie_ask`, `genie_poll_response`)",
        "extra": "instructions_a.md",
    },
    "custom_agent": {
        "display_name": "hoshi-supervisor-custom-agent",
        "description": "Hoshi Stream data assistant: two curated Genie Agents, a governed custom agent as the fallback.",
        "fallback_name": "`ask_fallback_agent` (governed fallback agent)",
        "extra": "instructions_b.md",
    },
}
# Routing examples shown to the supervisor. None of them may ask for the same thing as a benchmark
# question: scripts/check_overlap.py fails when one does.
EXAMPLES = [
    (
        "How many subscribers moved from monthly to annual billing this year?",
        ["Use subscribers_revenue.", "Do not use the fallback."],
    ),
    ("Which episodes in the catalogue run longest?", ["Use content_viewing.", "Do not use the fallback."]),
    (
        "Which licensors have a most favoured nations clause?",
        ["No curated agent covers licensing.", "Use the fallback."],
    ),
    (
        "Do gaming advertisers get more of their impressions on action series than on comedy?",
        ["Needs ad delivery joined to the catalogue in one query.", "Use the fallback."],
    ),
    (
        "Show me the contract terms for one of our voice actors.",
        ["Talent contracts are off limits.", "Refuse without calling any agent."],
    ),
]


def instructions(arm: str, cfg: dict) -> str:
    spec, brand, scope = ARMS[arm], cfg["brand"], cfg["scope"]

    def names(domains: list[str]) -> str:
        return ", ".join(f"`{schema(cfg, d)}`" for d in domains)

    common = (HERE / "instructions_common.md").read_text()
    extra = (HERE / spec["extra"]).read_text()
    return common.format(
        brand=brand,
        as_of=cfg["data"]["as_of"],
        fallback_name=spec["fallback_name"],
        fallback_covers=FALLBACK_COVERS.format(brand=brand),
    ) + extra.format(
        brand=brand,
        fallback_schemas=names(scope["fallback"]),
        join_schemas=names([d for d in scope["join_only"] if d not in scope["fallback"]]),
        off_limits_schemas=names(scope["off_limits"]),
    )


def tools(arm: str, cfg: dict, state: dict) -> dict[str, dict]:
    wanted = {
        tool_id: {
            "tool_type": "genie_space",
            "description": description,
            "genie_space": {"id": state["genie_spaces"][tool_id]},
        }
        for tool_id, description in GENIE_TOOLS.items()
    }
    covers = FALLBACK_COVERS.format(brand=cfg["brand"])
    if arm == "genie_one":
        wanted["genie_one"] = {
            "tool_type": "uc_mcp",
            "description": f"Genie One, the fallback for {covers} Always send the scope line first.",
            "uc_mcp": {"name": "system.ai.genie_one_mcp"},
        }
        wanted["hoshi_data_scope"] = {
            "tool_type": "skill",
            "description": "The approved Hoshi Stream tables, metric views and dashboard that Genie One may use.",
            "skill": {"name": state["uc_skill"]},
        }
    else:
        wanted["fallback_agent"] = {
            "tool_type": "app",
            "description": f"Governed fallback agent for {covers} It only reads approved tables.",
            "app": {"name": state["fallback_app"]},
        }
    return wanted


def upsert(arm: str, cfg: dict, state: dict) -> dict:
    profile, spec, text = cfg["workspace"]["profile"], ARMS[arm], instructions(arm, cfg)
    existing = json.loads(cli("supervisor-agents", "list-supervisor-agents", "-o", "json", profile=profile))
    match = next((s for s in existing if s["display_name"] == spec["display_name"]), None)
    if match:
        out = cli(
            "supervisor-agents", "update-supervisor-agent", match["name"], "description,instructions",
            spec["display_name"], "--description", spec["description"], "--instructions", text, "-o", "json",
            profile=profile,
        )  # fmt: skip
    else:
        out = cli(
            "supervisor-agents", "create-supervisor-agent", spec["display_name"],
            "--description", spec["description"], "--instructions", text, "-o", "json", profile=profile,
        )  # fmt: skip
    supervisor = json.loads(out)
    sid = supervisor["supervisor_agent_id"]

    # Tools: add what is missing first, then remove what is no longer wanted, so the supervisor
    # is never left without its agents if a call fails half way.
    def same_target(live: dict, body: dict) -> bool:
        """The live tool points at what `body` asks for. The service adds fields of its own, so only ours are compared."""
        kind = body["tool_type"]
        return live["tool_type"] == kind and all((live.get(kind) or {}).get(k) == v for k, v in body[kind].items())

    wanted = tools(arm, cfg, state)
    current = api("get", f"{API}/{sid}/tools", cfg).get("tools", [])
    for tool_id, body in wanted.items():
        live = next((t for t in current if same_target(t, body)), None)
        if live is None:
            try:
                api("post", f"{API}/{sid}/tools?tool_id={tool_id}", cfg, body)
            except RuntimeError as e:
                # Skill tools are a workspace preview. Without it, the scope still reaches Genie One
                # through the supervisor instructions, the Genie One skill and the workspace instructions.
                if body["tool_type"] != "skill" or "not enabled" not in str(e):
                    raise
                print(f"  note: skill tools are not enabled in this workspace, skipped {tool_id}")
        elif live.get("description") != body["description"]:
            api("patch", f"{API}/{sid}/tools/{live['tool_id']}?update_mask=description", cfg,
                {"tool_type": body["tool_type"], "description": body["description"]})  # fmt: skip
    for live in current:
        if not any(same_target(live, body) for body in wanted.values()):
            api("delete", f"{API}/{sid}/tools/{live['tool_id']}", cfg)
    attached = len(api("get", f"{API}/{sid}/tools", cfg).get("tools", []))

    # Examples: the same, so a change to EXAMPLES reaches a supervisor that already exists.
    live_examples = api("get", f"{API}/{sid}/examples", cfg).get("examples", [])
    have = {(e["question"], tuple(e.get("guidelines", []))): e for e in live_examples}
    want = {(question, tuple(guidelines)) for question, guidelines in EXAMPLES}
    for question, guidelines in want - set(have):
        api("post", f"{API}/{sid}/examples", cfg, {"question": question, "guidelines": list(guidelines)})
    for key in set(have) - want:
        api("delete", f"{API}/{sid}/examples/{have[key]['example_id']}", cfg)

    print(f"{arm}: {spec['display_name']} -> {supervisor['endpoint_name']} ({attached} tools)")
    return {"id": sid, "endpoint": supervisor["endpoint_name"], "experiment_id": supervisor.get("experiment_id")}


def main():
    cfg, state = load_config(), load_state()
    arms = sys.argv[1:] or list(ARMS)
    supervisors = state.get("supervisors", {})
    for arm in arms:
        supervisors[arm] = upsert(arm, cfg, state)
    save_state(supervisors=supervisors)


if __name__ == "__main__":
    main()
