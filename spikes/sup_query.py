"""Spike: query a supervisor endpoint, auto-approving MCP approval requests."""
import json
import os
import subprocess
import sys
import time

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT")


def post(endpoint, payload):
    out = subprocess.run(
        ["databricks", "api", "post", f"/serving-endpoints/{endpoint}/invocations", "--profile", PROFILE,
         "--json", json.dumps(payload)], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(out.stderr[-1500:])
    return json.loads(out.stdout)


def ask(endpoint, question):
    items = [{"role": "user", "content": question}]
    started = time.time()
    for _ in range(8):
        resp = post(endpoint, {"input": items})
        output = resp["output"]
        approvals = [o for o in output if o.get("type") == "mcp_approval_request"]
        items += output
        if not approvals:
            break
        items += [{"type": "mcp_approval_response", "approval_request_id": a["id"], "approve": True} for a in approvals]
    return items, time.time() - started


items, secs = ask(sys.argv[1], sys.argv[2])
for o in items:
    t = o.get("type")
    if t == "function_call" or t == "mcp_call":
        print("CALL", t, o.get("name"), str(o.get("arguments"))[:160], "| OUT:", str(o.get("output"))[:700] if o.get("output") else "")
    elif t == "function_call_output":
        print("OUT ", str(o.get("output"))[:700])
    elif t == "message":
        print("MSG ", json.dumps(o.get("content"))[:700])
    elif t:
        print(t.upper(), json.dumps(o)[:300])
print(f"{secs:.0f}s")
json.dump(items, open("spikes/out/last_items.json", "w"), indent=1)
