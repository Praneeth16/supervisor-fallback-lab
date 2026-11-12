"""Spike: call the managed Genie One MCP directly and print what comes back."""
import json
import os
import subprocess
import sys
import time

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT")
PATH = "/ai-gateway/mcp-services/system.ai.genie_one_mcp"


def call(tool, arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    out = subprocess.run(
        ["databricks", "api", "post", PATH, "--profile", PROFILE, "--json", json.dumps(body)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(out.stderr or out.stdout)
    return json.loads(out.stdout)["result"]


def main():
    question = sys.argv[1]
    started = time.time()
    res = call("genie_ask", {"question": question})
    structured = res.get("structuredContent") or {}
    print("ask keys:", list(res.keys()), "| structured keys:", list(structured.keys()))
    conv, resp = structured.get("conversation_id"), structured.get("response_id")
    status = structured.get("status")
    while status not in ("completed", "failed", "cancelled", "error"):
        time.sleep(5)
        res = call("genie_poll_response", {"conversation_id": conv, "response_id": resp})
        structured = res.get("structuredContent") or {}
        status = structured.get("status")
        print(f"  [{time.time() - started:5.0f}s] status={status}")
        if time.time() - started > 300:
            break
    print("---- structured (truncated) ----")
    print(json.dumps(structured, indent=1)[:6000])
    print("---- content text ----")
    for c in res.get("content", []):
        if c.get("type") == "text":
            print(c["text"][:4000])


main()
