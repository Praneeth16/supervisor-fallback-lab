"""The list of tool calls the agent made for one question, for the footer of its answer.

The line is built by code from the run's items, so it shows what really happened and not what the
model says happened. The lab UI reads it to show the agent's steps.
"""

import json

MAX_PATTERN_CHARS = 60


def _short_table(name: str) -> str:
    """schema.table, without the catalog."""
    parts = str(name).strip().strip("`").replace("`", "").split(".")
    return ".".join(parts[-2:])


def _one_line(text: str) -> str:
    # ";" separates steps and '"' wraps a pattern, so neither may appear inside one.
    return " ".join(str(text).replace(";", " ").replace('"', "'").split())[:MAX_PATTERN_CHARS]


def _sql_outcome(output) -> str:
    if output is None:
        return "error"
    output = str(output)
    if output.startswith("REJECTED"):
        return "rejected"
    if output.startswith("SQL ERROR"):
        return "error"
    return "ok"


def tool_steps(items: list[dict]) -> list[str]:
    """One entry for each tool call, in the order the agent made them.

    `items` are the run's new items in Responses API input form: function_call items carry the tool
    name and arguments, function_call_output items carry what the tool returned.
    """
    outputs = {i.get("call_id"): i.get("output") for i in items if i.get("type") == "function_call_output"}
    steps = []
    for item in items:
        if item.get("type") != "function_call":
            continue
        name = item.get("name") or "tool"
        try:
            arguments = json.loads(item.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if name == "read_table":
            steps.append(f"read_table {_short_table(arguments.get('table', ''))}")
        elif name == "search_tables":
            steps.append(f'search_tables "{_one_line(arguments.get("pattern", ""))}"')
        elif name == "run_sql":
            steps.append(f"run_sql {_sql_outcome(outputs.get(item.get('call_id')))}")
        else:
            steps.append(name)
    return steps


def steps_line(items: list[dict]) -> str | None:
    """`Steps: list_tables; read_table sales.campaign; run_sql ok`, or None when no tool was called."""
    steps = tool_steps(items)
    return "Steps: " + "; ".join(steps) if steps else None
