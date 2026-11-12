"""Client for Agent Bricks Supervisor Agent endpoints, shared by the UI backend and the evaluation.

A supervisor answers in Responses API format. Calls to a Databricks App tool come back as
`mcp_approval_request` items first. This client approves requests for the tools named in
`approve_tools`, declines every other request, and calls again until the supervisor produces a
final answer. Each call asks the endpoint to return its MLflow trace, which carries the trace id
and the tokens the supervisor's own model used.
"""

import json
import time
from dataclasses import dataclass, field

import requests
from databricks.sdk import WorkspaceClient

MAX_ROUNDS = 10
# The only app tool the lab's supervisors may call on the user's behalf.
APPROVE_TOOLS = ("ask_fallback_agent",)


@dataclass
class Turn:
    """Everything the supervisor produced for one user message."""

    items: list[dict] = field(default_factory=list)  # new items only, in order
    latency_s: float = 0.0
    error: str | None = None
    approvals: int = 0
    declined: list[str] = field(default_factory=list)  # tools whose approval request was declined
    trace_ids: list[str] = field(default_factory=list)  # one per call to the endpoint
    supervisor_tokens: int = 0  # tokens used by the supervisor's own model, from its traces


def _post(w: WorkspaceClient, endpoint: str, items: list[dict], timeout_s: int) -> dict:
    response = requests.post(
        f"{w.config.host}/serving-endpoints/{endpoint}/invocations",
        headers={**w.config.authenticate(), "Content-Type": "application/json"},
        json={"input": items, "databricks_options": {"return_trace": True}},
        timeout=timeout_s,
    )
    body = response.text
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {body[:500]}")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Errors inside a supervisor run arrive as an event stream with HTTP 200.
        for line in body.splitlines():
            if line.startswith("data: {"):
                raise RuntimeError(json.loads(line[6:]).get("message", line)) from None
        raise RuntimeError(f"Unreadable response: {body[:300]}") from None


def _record_trace(turn: Turn, response: dict) -> None:
    info = ((response.get("databricks_output") or {}).get("trace") or {}).get("info") or {}
    if info.get("trace_id"):
        turn.trace_ids.append(info["trace_id"])
    usage = (info.get("trace_metadata") or {}).get("mlflow.trace.tokenUsage")
    if usage:
        try:
            turn.supervisor_tokens += int(json.loads(usage).get("total_tokens") or 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass


def ask(
    w: WorkspaceClient,
    endpoint: str,
    history: list[dict],
    timeout_s: int = 600,
    approve_tools: tuple[str, ...] = APPROVE_TOOLS,
) -> Turn:
    """Send the conversation in `history` (ending with a user message) and return the new items."""
    turn = Turn()
    conversation = list(history)
    started = time.monotonic()
    try:
        for _ in range(MAX_ROUNDS):
            response = _post(w, endpoint, conversation, timeout_s)
            _record_trace(turn, response)
            output = response["output"]
            turn.items += output
            pending = [o for o in output if o.get("type") == "mcp_approval_request"]
            if not pending:
                break
            answers = []
            for request in pending:
                approved = request.get("name") in approve_tools
                answers.append(
                    {"type": "mcp_approval_response", "approval_request_id": request["id"], "approve": approved}
                )
                if approved:
                    turn.approvals += 1
                else:
                    turn.declined.append(str(request.get("name")))
            turn.items += answers
            conversation = list(history) + turn.items
        else:
            turn.error = f"No final answer after {MAX_ROUNDS} approval rounds."
    except (requests.RequestException, RuntimeError, KeyError) as e:
        turn.error = str(e) or type(e).__name__
    turn.latency_s = round(time.monotonic() - started, 2)
    return turn
