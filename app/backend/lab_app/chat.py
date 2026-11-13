"""Turns the supervisor's event stream into the steps the chat page shows while an answer is made.

A supervisor emits finished output items one by one: its own short notes, tool calls, tool results
and approval requests. `StepBuilder` reads them in order and produces steps in plain words: which
agent was asked, what Genie One said it was doing, what the custom agent ran. Each step has a stable
id, so a later event can update an earlier step, for example from running to done.
"""

import json
import re
import time
from collections.abc import Iterator

from labcore import parse, supervisor

_MARKER = re.compile(r"^\s*<name>[^<]*</name>\s*$")
_BULLET = re.compile(r"^\s*[•*-]\s+(.+)$", re.MULTILINE)
_PROGRESS_HEAD = re.compile(r"Still running\.?\s*(\d+)\s+progress step", re.IGNORECASE)
_LINK = re.compile(r"\[Explore in Databricks\]\((https?://[^)\s]+)\)")
_GENIE_PREFIX = re.compile(r"^(Thinking:\s*)?Genie:\s*\w+\s*[—-]\s*", re.IGNORECASE)
_FOOTER_LINE = re.compile(
    r"^(Tables used|Steps|Queries blocked by the scope guard|Queries ran as|Agent tokens):\s*(.+)$"
)
MAX_DETAIL = 600


def _text_of(item: dict) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content or [] if isinstance(p, dict))


def _argument(item: dict, *names: str) -> str:
    try:
        arguments = json.loads(item.get("arguments") or "{}")
    except (json.JSONDecodeError, TypeError):
        return ""
    for name in names:
        if isinstance(arguments.get(name), str):
            return arguments[name]
    return next((v for v in arguments.values() if isinstance(v, str)), "")


def _clip(text: str, limit: int = MAX_DETAIL) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _tidy_progress(line: str) -> str:
    """One progress line of Genie One, without its prefix and without the result table it may carry."""
    text = re.sub(r"^Thinking:\s*", "", _GENIE_PREFIX.sub("", line).strip())
    if text.startswith("Query result:"):
        text = text.split("<!--")[0].split("|")[0].replace("Query result:", "").strip().rstrip(":")
    return _clip(" ".join(text.split()), 220)


def agent_footer(output: str) -> dict:
    """Facts from the footer the custom agent's code adds to every answer."""
    facts: dict = {"tables": [], "steps": [], "blocked": 0, "identity": None, "tokens": None}
    if parse._AGENT_FOOTER not in output:
        return facts
    footer = output.rsplit(parse._AGENT_FOOTER, 1)[1]
    for line in footer.splitlines():
        match = _FOOTER_LINE.match(line.strip())
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "Tables used":
            facts["tables"] = [t.strip() for t in value.split(",") if t.strip()]
        elif key == "Steps":
            facts["steps"] = [s.strip() for s in value.split(";") if s.strip()]
        elif key == "Queries blocked by the scope guard":
            facts["blocked"] = int(re.sub(r"\D", "", value) or 0)
        elif key == "Queries ran as":
            facts["identity"] = value
        elif key == "Agent tokens":
            facts["tokens"] = int(re.sub(r"\D", "", value) or 0)
    return facts


class StepBuilder:
    """Feed it the pairs from `supervisor.ask_stream`. It returns the steps that changed."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._started = clock()
        self._steps: dict[str, dict] = {}
        self._order: list[str] = []
        self._progress_seen = 0
        self._genie_one_step: str | None = None
        self._note_count = 0

    @property
    def steps(self) -> list[dict]:
        return [self._steps[key] for key in self._order]

    def _now(self) -> float:
        return round(self._clock() - self._started, 1)

    def _put(self, key: str, **fields) -> dict:
        step = self._steps.get(key)
        if step is None:
            step = {"id": key, "kind": "call", "route": None, "title": "", "detail": None, "status": "done",
                    "t": self._now(), "duration_s": None, "sql": [], "tables": [], "link": None}  # fmt: skip
            self._steps[key] = step
            self._order.append(key)
        step.update(fields)
        return step

    def _finish(self, key: str, **fields) -> dict:
        step = self._steps[key]
        fields.setdefault("status", "done")
        return self._put(key, duration_s=round(self._now() - step["t"], 1), **fields)

    def feed(self, kind: str, payload) -> list[dict]:
        if kind == "approval":
            key = payload["approval_request_id"]
            if key not in self._steps:
                return []
            if payload["approve"]:
                return [self._put(key, title="Custom agent is working on it", status="running")]
            return [self._finish(key, title="Tool call declined", status="failed")]
        if kind != "item":
            return []
        item = payload
        item_type = item.get("type")
        if item_type == "message":
            return self._message(item)
        if item_type == "function_call":
            return self._call(item)
        if item_type == "mcp_approval_request":
            return [
                self._put(
                    item["id"], kind="call", route=parse.route_of(item.get("name", "")), status="running",
                    title="Asked for approval to call the custom agent", detail=_clip(_argument(item, "question")),
                )
            ]  # fmt: skip
        if item_type in ("function_call_output", "mcp_call"):
            return self._result(item)
        return []

    def _message(self, item: dict) -> list[dict]:
        text = _text_of(item)
        if not text.strip() or _MARKER.match(text):
            return []
        call_id = item.get("call_id")
        if call_id and call_id in self._steps:
            # A curated Genie Agent hands its result back as a message that carries the call id.
            return [self._finish(call_id, result=_clip(text, 4000))]
        self._note_count += 1
        return [self._put(f"note-{self._note_count}", kind="note", title=_clip(text, 1200))]

    def _call(self, item: dict) -> list[dict]:
        name = item.get("name", "")
        route = parse.route_of(name)
        key = item.get("call_id") or item.get("id") or name
        if route == "genie_one":
            if "poll" in name or "get_query_result" in name:
                return []
            self._genie_one_step = key
            return [
                self._put(key, route=route, status="running", title="Sent the question to Genie One",
                          detail=_clip(_argument(item, "question")))
            ]  # fmt: skip
        if route.startswith("genie:"):
            return [
                self._put(key, route=route, status="running", title="Asked a curated Genie Agent",
                          detail=_clip(_argument(item, "genie_query", "query", "question", "input")))
            ]  # fmt: skip
        if route == "fallback_agent":
            return [
                self._put(key, route=route, status="running", title="Custom agent is working on it",
                          detail=_clip(_argument(item, "question")))
            ]  # fmt: skip
        return [self._put(key, route=route, status="running", title=f"Called {name}", detail=_clip(_argument(item)))]

    def _result(self, item: dict) -> list[dict]:
        name = item.get("name", "")
        route = parse.route_of(name)
        key = item.get("call_id") or item.get("id") or name
        output = item.get("output")
        text = output if isinstance(output, str) else json.dumps(output or "")
        if route == "genie_one":
            return self._genie_one_result(name, key, text)
        if key not in self._steps:
            self._put(key, route=route, title=f"Called {name}")
        if route == "fallback_agent":
            return self._custom_agent_result(key, text)
        ran, _ = parse._split_agent_output(text)
        return [self._finish(key, sql=list(dict.fromkeys(ran)), result=_clip(text, 4000))]

    def _genie_one_result(self, name: str, key: str, text: str) -> list[dict]:
        step_key = self._genie_one_step or key
        if step_key not in self._steps:
            self._put(step_key, route="genie_one", status="running", title="Sent the question to Genie One")
            self._genie_one_step = step_key
        changed = []
        link = _LINK.search(text)
        if link and not self._steps[step_key]["link"]:
            changed.append(self._put(step_key, link=link.group(1)))
        if "genie_ask" in name:
            return changed
        head = _PROGRESS_HEAD.search(text)
        if head:
            bullets = [_tidy_progress(b) for b in _BULLET.findall(text.split("Briefly share")[0])]
            for bullet in bullets[self._progress_seen :]:
                self._progress_seen += 1
                changed.append(
                    self._put(f"{step_key}-p{self._progress_seen}", kind="progress", route="genie_one", title=bullet)
                )
            if not bullets:
                changed.append(self._put(step_key, title="Genie One is working on it", status="running"))
            return changed
        if "Still running" in text:
            return changed + [self._put(step_key, title="Genie One is working on it", status="running")]
        ran = list(dict.fromkeys(parse._sql_in(text)))
        failed = bool(re.search(r"\*\*Status:\*\*\s*(failed|error|cancelled)", text, re.IGNORECASE))
        tables = sorted({t for statement in ran for t in parse.tables_in(statement)})
        # The finished call belongs after the progress lines Genie One reported on the way.
        self._order.remove(step_key)
        self._order.append(step_key)
        return [
            self._finish(step_key, title="Genie One could not finish" if failed else "Genie One answered",
                         status="failed" if failed else "done", sql=ran, tables=tables)
        ]  # fmt: skip

    def _custom_agent_result(self, key: str, text: str) -> list[dict]:
        ran, _ = parse._split_agent_output(text)
        ran = list(dict.fromkeys(ran))
        facts = agent_footer(text)
        changed = []
        for index, inner in enumerate(facts["steps"], start=1):
            changed.append(self._put(f"{key}-s{index}", kind="progress", route="fallback_agent", title=inner))
        blocked = facts["blocked"]
        title = "Custom agent answered"
        if blocked:
            title += f". The scope guard blocked {blocked} {'query' if blocked == 1 else 'queries'}"
        changed.append(self._finish(key, title=title, sql=ran, tables=facts["tables"], facts=facts))
        # The finished call belongs after the agent's own steps in the list.
        self._order.remove(key)
        self._order.append(key)
        return changed


def run_turn(client, endpoint: str, history: list[dict], allowed_tables: frozenset[str]) -> Iterator[dict]:
    """Ask a supervisor and yield events for the browser: step, delta, and one final event."""
    builder = StepBuilder()
    for kind, payload in supervisor.ask_stream(client, endpoint, history):
        if kind == "delta":
            yield {"event": "delta", "text": payload}
            continue
        if kind == "turn":
            yield final_event(payload, builder.steps, allowed_tables)
            return
        if kind == "item" and payload.get("type") == "message" and not _MARKER.match(_text_of(payload)):
            yield {"event": "message", "text": _text_of(payload), "tool_result": bool(payload.get("call_id"))}
        for step in builder.feed(kind, payload):
            yield {"event": "step", "step": step}


def final_event(turn: supervisor.Turn, steps: list[dict], allowed_tables: frozenset[str]) -> dict:
    facts = parse.extract(turn.items, allowed_tables)
    # The supervisor's last note is the answer, so it does not belong among the steps.
    notes = [s for s in steps if s["kind"] == "note"]
    if notes and facts.answer and notes[-1]["title"].rstrip("…") in facts.answer:
        steps = [s for s in steps if s is not notes[-1]]
    for step in steps:
        if step["status"] == "running":
            step["status"] = "failed" if turn.error else "done"
    return {
        "event": "final",
        "answer": facts.answer,
        "routes": facts.routes,
        "sql": facts.sql,
        "tables": facts.tables,
        "out_of_scope_tables": facts.out_of_scope,
        "latency_s": turn.latency_s,
        "approvals": turn.approvals,
        "error": turn.error,
        "trace_id": turn.trace_ids[-1] if turn.trace_ids else None,
        "supervisor_tokens": turn.supervisor_tokens,
        "steps": steps,
    }


def replay(items: list[dict], reply: dict, pace_s: float = 0.0) -> Iterator[dict]:
    """Events for a saved transcript. Used with fixture data, so the page works without a workspace."""
    builder = StepBuilder()
    for item in items:
        if pace_s:
            time.sleep(pace_s)
        if item.get("type") == "message" and not _MARKER.match(_text_of(item)):
            text = _text_of(item)
            for start in range(0, len(text), 24):
                if pace_s:
                    time.sleep(pace_s / 12)
                yield {"event": "delta", "text": text[start : start + 24]}
            yield {"event": "message", "text": text, "tool_result": bool(item.get("call_id"))}
        kind = "approval" if item.get("type") == "mcp_approval_response" else "item"
        payload = {**item, "name": "ask_fallback_agent"} if kind == "approval" else item
        for step in builder.feed(kind, payload):
            yield {"event": "step", "step": step}
    steps = builder.steps
    notes = [s for s in steps if s["kind"] == "note"]
    if notes and notes[-1]["title"].rstrip("…") in (reply.get("answer") or ""):
        steps = [s for s in steps if s is not notes[-1]]
    for step in steps:
        if step["status"] == "running":
            step["status"] = "done"
    yield {
        "event": "final",
        "answer": reply.get("answer", ""),
        "routes": reply.get("routes", []),
        "sql": reply.get("sql", []),
        "tables": reply.get("tables", []),
        "out_of_scope_tables": reply.get("out_of_scope_tables", []),
        "latency_s": reply.get("latency_s", 0.0),
        "approvals": reply.get("approvals", 0),
        "error": reply.get("error"),
        "trace_id": reply.get("trace_id"),
        "supervisor_tokens": reply.get("supervisor_tokens", 0),
        "steps": steps,
    }
