# Spike findings (2026-11-11)

Short tests run before the build, on workspace profile `<profile>`. Each one changed
the design, so they are kept here for anyone repeating the lab elsewhere.

| # | Question | Result |
|---|---|---|
| 1 | Can a Supervisor Agent attach the managed Genie One MCP? | Yes. Tool body `{"tool_type": "uc_mcp", "uc_mcp": {"name": "system.ai.genie_one_mcp"}}` posted to `/api/2.1/supervisor-agents/{id}/tools?tool_id=...`. CLI 1.25 `create-tool --json` drops the `uc_mcp` field, so the REST path is used. |
| 2 | Whose identity does Genie One run as behind the supervisor? | The calling user. `SELECT current_user()` returned the caller. |
| 3 | Do Genie One skills and workspace instructions apply on the MCP path? | Yes, both. A personal skill and `/Workspace/.genie_workspace_instructions.md` were both applied to `genie_ask` calls. |
| 4 | Does the supervisor pass the question through unchanged? | No. By default it rewrote the question and dropped the words that trigger the skill. With an explicit "pass verbatim" instruction it kept them. Scope rules therefore must not depend on trigger words surviving. |
| 5 | How does a supervisor attach a custom agent app? | As an MCP server. The app must serve MCP at `/mcp`; a plain Responses API app fails with "Failed to register tools from Databricks App MCP server". |
| 6 | Does a call to an app tool run straight away? | No. The supervisor returns `mcp_approval_request` items. The client must answer each with `{"type": "mcp_approval_response", "approval_request_id": ..., "approve": true}` and call again. Genie One (`uc_mcp`) needed no approval. |
| 7 | Is the user's identity forwarded to the app? | Yes. The app saw `x-forwarded-access-token` and its SQL ran as the caller (app `user_api_scopes`: `sql`, `ai-gateway`). |
| 8 | Do LLM and SQL calls work through Unity Gateway? | Yes. LLM at `/ai-gateway/mlflow/v1` with model `system.ai.claude-sonnet-5-5`; SQL through MCP service `system.ai.dbsql`. |
| 9 | Anything unexpected? | The supervisor has a built-in `sandbox` tool and once tried to run SQL with it instead of delegating. Supervisor instructions forbid it and the evaluation counts it. |

Response format: supervisor responses follow the Responses API. Tool use appears as `function_call`
and `function_call_output` items, so the route taken and the SQL run can be read from the response.
