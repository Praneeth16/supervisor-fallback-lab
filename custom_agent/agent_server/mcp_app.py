"""MCP face of the agent. A Supervisor Agent attaches a Databricks App as an MCP server, so the
whole agent is exposed as one tool: a question goes in, an answer with its SQL comes out."""

import contextvars

import mlflow
from fastmcp import FastMCP

from agent_server.agent import answer, final_text

request_headers: contextvars.ContextVar[dict | None] = contextvars.ContextVar("request_headers", default=None)

mcp_server = FastMCP(name="hoshi-fallback-agent")


@mcp_server.tool
@mlflow.trace(name="ask_fallback_agent", span_type="AGENT")
async def ask_fallback_agent(question: str) -> str:
    """Ask the governed fallback data agent a question in plain language.

    Use it for Hoshi Stream data questions that no curated Genie Agent covers: content licensing
    and rights, royalties, advertising sales and delivery, partner deals and minimum guarantees,
    and questions that join those to subscriber, billing, content or viewing data. It writes SQL
    over an approved list of tables only, and refuses anything outside that list. The answer ends
    with the tables used and the SQL that was run.

    Args:
        question: The user's question, word for word, with any context needed to answer it.
    """
    token = (request_headers.get() or {}).get("x-forwarded-access-token")
    items, _ = await answer([{"role": "user", "content": question}], token)
    return final_text(items)


mcp_app = mcp_server.http_app(stateless_http=True)
