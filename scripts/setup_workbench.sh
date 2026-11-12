#!/usr/bin/env bash
# Deploy the Genie Workbench app that builds the lab's Genie Agents (make agents).
# Scripted from the manual deploy of 2026-11-11 (.vendor/deploy-run-1.log). Not yet run end to end.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
REPO_URL="https://github.com/databricks-solutions/databricks-genie-workbench"
PIN="44a3705b68ff4bf90eee82e81a94f20c9cc237bf"
VENDOR="$ROOT/.vendor/databricks-genie-workbench"
APP="genie-workbench-hoshi"
SCOPES="ai-gateway catalog.catalogs:read catalog.schemas:read catalog.tables:read dashboards.genie files.files genie serving.serving-endpoints sql"

[ -x "$PY" ] || { echo "Missing $PY. Run make setup first." >&2; exit 1; }

read -r PROFILE WAREHOUSE CATALOG <<<"$("$PY" - "$ROOT" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from labconfig import load_config
w = load_config()["workspace"]
print(w["profile"], w["warehouse_id"], w["catalog"])
EOF
)"

if [ ! -d "$VENDOR/.git" ]; then
    mkdir -p "$ROOT/.vendor"
    git clone --quiet "$REPO_URL" "$VENDOR"
fi
git -C "$VENDOR" cat-file -e "$PIN^{commit}" 2>/dev/null || git -C "$VENDOR" fetch --quiet origin
git -C "$VENDOR" checkout --quiet --detach "$PIN"

umask 077
cat >"$VENDOR/.env.deploy" <<EOF
GENIE_WAREHOUSE_ID=$WAREHOUSE
GENIE_CATALOG=$CATALOG
GENIE_APP_NAME=$APP
GENIE_DEPLOY_PROFILE=$PROFILE
GENIE_LLM_ROUTE=gateway
EOF

# deploy.sh sets user_api_scopes without genie on every run, so the scope is added after it.
if databricks apps get "$APP" --profile "$PROFILE" >/dev/null 2>&1; then
    (cd "$VENDOR" && bash scripts/deploy.sh --update)
else
    (cd "$VENDOR" && bash scripts/deploy.sh)
fi

APP_JSON="$(databricks apps get "$APP" --profile "$PROFILE" -o json)"
if ! printf '%s' "$APP_JSON" | python3 -c 'import json,sys; sys.exit("genie" not in json.load(sys.stdin)["user_api_scopes"])'; then
    NEW_JSON="$(printf '%s' "$APP_JSON" | python3 -c '
import json, sys
app = json.load(sys.stdin)
scopes = sys.argv[1].split()
print(json.dumps({"name": app["name"], "resources": app["resources"], "user_api_scopes": scopes}))
' "$SCOPES")"
    databricks apps update "$APP" --profile "$PROFILE" --json "$NEW_JSON" >/dev/null
    databricks apps stop "$APP" --profile "$PROFILE"
    databricks apps start "$APP" --profile "$PROFILE"
    DEPLOYER="$(databricks current-user me --profile "$PROFILE" -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["userName"])')"
    databricks apps deploy "$APP" --profile "$PROFILE" --source-code-path "/Workspace/Users/$DEPLOYER/$APP"
    APP_JSON="$(databricks apps get "$APP" --profile "$PROFILE" -o json)"
fi

URL="$(printf '%s' "$APP_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
printf '%s' "$APP_JSON" | python3 -c 'import json,sys; sys.exit("genie" not in json.load(sys.stdin)["user_api_scopes"])' \
    || { echo "The genie scope is still missing on $APP." >&2; exit 1; }

"$PY" - "$ROOT" "$APP" "$URL" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from labconfig import save_state
save_state(workbench_app=sys.argv[2], workbench_url=sys.argv[3])
EOF
echo "Genie Workbench is up at $URL (saved to state.json)"
