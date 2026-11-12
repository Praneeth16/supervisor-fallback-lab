# Install crash/hang/exception diagnostics before importing agent code so
# startup failures and unhandled exceptions land in the Apps log stream.
from scripts.app_diagnostics import install_diagnostics

install_diagnostics()

import os

import uvicorn
from fastapi import FastAPI, Request
from mlflow.genai.agent_server import AgentServer

# Importing mcp_app also imports the agent, which registers its invoke and stream functions.
from agent_server.mcp_app import mcp_app, request_headers

agent_server = AgentServer("ResponsesAgent")

# One app, two faces: /mcp for supervisors (MCP), /invocations for direct Responses API calls.
app = FastAPI(
    title="Hoshi fallback agent",
    routes=[*mcp_app.routes, *agent_server.app.routes],
    lifespan=mcp_app.lifespan,
)


@app.middleware("http")
async def capture_headers(request: Request, call_next):
    request_headers.set(dict(request.headers))
    return await call_next(request)


def main():
    uvicorn.run(
        "agent_server.start_server:app",
        host="0.0.0.0",
        port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
    )
