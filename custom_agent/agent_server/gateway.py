"""SQL execution through the Databricks SQL MCP server behind Unity Gateway.

Going through the gateway (instead of a direct warehouse connection) means every statement is
recorded in `system.ai_gateway.usage` and `system.access.audit` under the caller's identity.
"""

import time

from databricks.sdk import WorkspaceClient

DBSQL_MCP_PATH = "/ai-gateway/mcp-services/system.ai.dbsql"
_PENDING = {"PENDING", "RUNNING"}


def _call(w: WorkspaceClient, tool: str, arguments: dict) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    response = w.api_client.do("POST", DBSQL_MCP_PATH, body=body)
    if "error" in response:
        raise RuntimeError(response["error"].get("message", str(response["error"])))
    result = response["result"]
    if result.get("isError"):
        raise RuntimeError(" ".join(c.get("text", "") for c in result.get("content", [])))
    return result["structuredContent"]


def _cell(value: dict):
    """One result cell: {"str": "x"} or {"string_value": "x"}, and {} or {"null_value": ...} for NULL."""
    if not value or "null_value" in value:
        return None
    return next(iter(value.values()))


def run_statement(w: WorkspaceClient, sql: str, timeout_s: int = 180) -> dict:
    """Run one statement and return {"columns": [...], "rows": [[...]], "row_count": n, "truncated": bool}."""
    deadline = time.monotonic() + timeout_s
    out = _call(w, "execute_sql", {"query": sql})
    while out.get("status", {}).get("state") in _PENDING:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Statement still running after {timeout_s}s.")
        time.sleep(2)
        out = _call(w, "poll_sql_result", {"statement_id": out["statement_id"]})

    status = out.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(status.get("error", {}).get("message") or f"Statement {status.get('state')}.")

    columns = [c["name"] for c in out.get("manifest", {}).get("schema", {}).get("columns", [])]
    result = out.get("result", {})
    # The gateway answers in one of two shapes depending on the result format.
    raw_rows = result.get("data_typed_array") or result.get("data_array") or []
    rows = [[_cell(v) for v in row.get("values", [])] for row in raw_rows]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": out.get("total_row_count", len(rows)),
        "truncated": bool(out.get("truncated")),
    }
