"""Governed text-to-SQL fallback agent.

Design borrowed from nao: the model explores a folder of table descriptions, writes SQL, and a
guard decides whether that SQL may run. Everything Databricks-native: the LLM and the SQL both
go through Unity Gateway, tables are Unity Catalog tables, traces go to MLflow.
"""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from uuid import uuid4

import mlflow
from agents import Agent, RunContextWrapper, Runner, function_tool, set_default_openai_api, set_default_openai_client
from agents.tracing import set_trace_processors
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks_openai import AsyncDatabricksOpenAI
from mlflow.genai.agent_server import get_request_headers, invoke, stream
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse, ResponsesAgentStreamEvent

from agent_server.gateway import run_statement
from agent_server.guard import check_sql
from agent_server.history import normalize_history_items
from agent_server.scope import load_scope, read_table_doc, search_context

logger = logging.getLogger(__name__)

MODEL = os.environ.get("AGENT_MODEL", "system.ai.claude-sonnet-5-5")
MAX_ROWS_SHOWN = 50
# "off" turns the table allowlist off. It exists only for the guard-off ablation app in the lab.
GUARD_ENFORCED = os.environ.get("AGENT_GUARD", "enforce") != "off"
# In the deployed app SQL must run as the caller. Without a forwarded user token the agent stops,
# instead of quietly running with the app's own, broader identity.
REQUIRE_USER_TOKEN = os.environ.get("AGENT_REQUIRE_USER_TOKEN", "0") == "1"
NO_USER_TOKEN = (
    "I can't answer this. This agent only runs queries with the caller's own identity, and no user "
    "token reached it with this request."
)

set_default_openai_client(AsyncDatabricksOpenAI(use_ai_gateway=True))
# The Responses API carries the model's reasoning items; with Chat Completions they break parsing.
set_default_openai_api("responses")
set_trace_processors([])  # MLflow is the only trace sink
mlflow.openai.autolog()

INSTRUCTIONS = """You answer data questions that no curated Genie Agent covers, by writing SQL over a
fixed set of Unity Catalog tables.

How to work:
1. Call list_tables to see what is in scope. Call read_table for every table you plan to use;
   never guess column names or values. Use search_tables to find a column or term.
2. Write one Databricks SQL SELECT with fully qualified names (catalog.schema.table) and call run_sql.
3. If run_sql answers REJECTED, the table or operation is outside your scope. Do not look for a
   workaround. If the question cannot be answered from tables in scope, say so plainly and name
   what is missing.
4. If run_sql says the result was cut at a row limit, the rows are not the whole result. Never
   report the number of rows returned as a count; run a COUNT query.
5. Answer in plain language with the key numbers. State any assumption you made (time range,
   definition of a metric). If the question is ambiguous in a way that changes the answer, ask
   one short clarifying question instead of guessing.

Never invent numbers. Never use tables that list_tables does not return.

{rules}"""


@dataclass
class RequestState:
    workspace_client: WorkspaceClient
    identity: str
    sql_run: list[str] = field(default_factory=list)
    tables_used: set[str] = field(default_factory=set)
    rejected: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    tokens: int = 0


def _request_state(user_token: str | None) -> RequestState:
    """SQL runs as the calling user when their token was forwarded, otherwise as the app."""
    if user_token:
        return RequestState(WorkspaceClient(token=user_token, auth_type="pat"), identity="user")
    return RequestState(WorkspaceClient(), identity="app")


def _markdown_table(result: dict, row_cap: int | None) -> str:
    cut = row_cap is not None and len(result["rows"]) > row_cap
    cols, rows = result["columns"], result["rows"][:MAX_ROWS_SHOWN]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    if cut:
        lines.append(
            f"\n(The result was cut at {row_cap} rows and has more. First {len(rows)} shown. "
            "This is not a row count; use COUNT(*) to count.)"
        )
    elif len(result["rows"]) > len(rows):
        lines.append(f"\n({len(result['rows'])} rows in total, first {len(rows)} shown)")
    return "\n".join(lines)


@function_tool
def list_tables() -> str:
    """List every table you are allowed to query, with a one-line description of each."""
    return load_scope().index


@function_tool
def read_table(table: str) -> str:
    """Read the description of one table: columns, types, meanings, keys and sample values.

    Args:
        table: Fully qualified table name, catalog.schema.table.
    """
    return read_table_doc(table)


@function_tool
def search_tables(pattern: str) -> str:
    """Search all table descriptions for a word or regular expression (case-insensitive).

    Args:
        pattern: Word or regular expression, for example "royalt" or "expir|end_date".
    """
    return search_context(pattern)


@function_tool
async def run_sql(ctx: RunContextWrapper[RequestState], sql: str) -> str:
    """Run one read-only SQL query and return the rows.

    Args:
        sql: A single Databricks SQL SELECT statement using fully qualified table names.
    """
    state = ctx.context
    verdict = check_sql(sql, load_scope().allowed if GUARD_ENFORCED else None)
    if not verdict.ok:
        state.rejected.append(sql)
        logger.info("guard rejected a query: %s", verdict.reason)
        return f"REJECTED: {verdict.reason}"
    try:
        result = await asyncio.to_thread(run_statement, state.workspace_client, verdict.sql)
    except (DatabricksError, RuntimeError, TimeoutError, KeyError, ValueError) as e:
        state.failed.append(verdict.sql)
        return f"SQL ERROR: {e}"  # the model reads the error and fixes its SQL
    state.sql_run.append(verdict.sql)
    state.tables_used.update(verdict.tables)
    return _markdown_table(result, verdict.row_cap)


def create_agent() -> Agent:
    return Agent(
        name="Fallback data agent",
        instructions=INSTRUCTIONS.format(rules=load_scope().rules),
        model=MODEL,
        tools=[list_tables, read_table, search_tables, run_sql],
    )


def _footer(state: RequestState) -> str:
    # The evaluation splits an answer at the "---" and "Source:" lines below: SQL under them ran, SQL
    # above them was only shown (app/backend/labcore/parse.py, _AGENT_FOOTER). Change both together.
    lines = ["", "", "---", "Source: tables that are not curated for self-service. Treat the figures as provisional."]
    if state.tables_used:
        lines.append("Tables used: " + ", ".join(sorted(state.tables_used)))
    for sql in state.sql_run:
        lines += ["```sql", sql, "```"]
    if state.rejected:
        lines.append(f"Queries blocked by the scope guard: {len(state.rejected)}")
    lines.append(f"Queries ran as: {'the calling user' if state.identity == 'user' else 'the agent app'}")
    lines.append(f"Agent tokens: {state.tokens:,}")
    return "\n".join(lines)


def _append_footer(items: list[dict], footer: str) -> list[dict]:
    """Add the code-built footer to the last assistant message, so callers that read only the
    final message still see which tables and SQL were used."""
    for item in reversed(items):
        if item.get("type") == "message" and item.get("role") == "assistant":
            content = item.get("content")
            if isinstance(content, str):
                item["content"] = content + footer
                return items
            for part in reversed(content or []):
                if part.get("type") == "output_text":
                    part["text"] += footer
                    return items
    items.append(
        {
            "type": "message",
            "id": str(uuid4()),
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": footer.lstrip(), "annotations": []}],
        }
    )
    return items


async def answer(messages: list[dict], user_token: str | None) -> tuple[list[dict], RequestState]:
    """Run the agent on a conversation and return its output items plus what it touched."""
    state = _request_state(user_token)
    if REQUIRE_USER_TOKEN and state.identity != "user":
        return _append_footer([], NO_USER_TOKEN), state
    result = await Runner.run(create_agent(), messages, context=state, max_turns=20)
    state.tokens = result.context_wrapper.usage.total_tokens
    items = _append_footer([item.to_input_item() for item in result.new_items], _footer(state))
    mlflow.update_current_trace(
        tags={
            "sql_identity": state.identity,
            "guard": "enforced" if GUARD_ENFORCED else "off",
            "tables_used": ",".join(sorted(state.tables_used)),
            "queries_rejected": str(len(state.rejected)),
            "agent_tokens": str(state.tokens),
        }
    )
    return items, state


def final_text(items: list[dict]) -> str:
    for item in reversed(items):
        if item.get("type") == "message" and item.get("role") == "assistant":
            content = item.get("content")
            if isinstance(content, str):
                return content
            return "".join(p.get("text", "") for p in content or [] if p.get("type") == "output_text")
    return ""


async def _run(request: ResponsesAgentRequest) -> tuple[list[dict], RequestState]:
    messages = normalize_history_items([i.model_dump() for i in request.input])
    return await answer(messages, get_request_headers().get("x-forwarded-access-token"))


@invoke()
async def invoke_handler(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    items, state = await _run(request)
    return ResponsesAgentResponse(
        output=items,
        custom_outputs={
            "sql_identity": state.identity,
            "guard": "enforced" if GUARD_ENFORCED else "off",
            "tables_used": sorted(state.tables_used),
            "sql_run": state.sql_run,
            "queries_rejected": state.rejected,
            "queries_failed": state.failed,
            "agent_tokens": state.tokens,
        },
    )


@stream()
async def stream_handler(request: ResponsesAgentRequest) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    # A sub-agent's callers need the finished items, not token deltas, so run to completion
    # and emit each item once. This keeps the footer attached to the final message.
    items, _ = await _run(request)
    for item in items:
        yield ResponsesAgentStreamEvent(type="response.output_item.done", item=item)
