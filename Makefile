# Supervisor fallback lab. Run make setup, edit lab.yaml, then run the targets top to bottom (README.md).
#
# Some targets replace or delete things in the workspace:
#   data           builds tables only when none exist. CONFIRM_REPLACE=1 rebuilds them and drops their data,
#                  and the generator then rewrites every row
#   scope          merges the lab section into the shared /Workspace/.genie_workspace_instructions.md (backup kept)
#   agent          redeploys the fallback agent app and rewrites its context folder
#   supervisors    updates the tools and instructions of both supervisors
#   app            redeploys the lab UI app
#   eval           adds a run under LABEL. Use a new LABEL for each run you want to keep
#   teardown       removes the Genie One scope. teardown-all removes the lab and needs CONFIRM=1

PY ?= .venv/bin/python

define lab_value
$(or $(shell $(PY) -c "import yaml;print(yaml.safe_load(open('lab.yaml'))$(1))" 2>/dev/null),$(error lab.yaml $(2) is empty or lab.yaml is missing: run make setup first, then edit lab.yaml))
endef

define state_value
$(or $(shell $(PY) -c "import json;print(json.load(open('state.json')).get('$(1)') or '')" 2>/dev/null),$(error state.json has no $(1): $(2)))
endef

PROFILE     = $(call lab_value,['workspace']['profile'],workspace.profile)
WH          = $(call lab_value,['workspace']['warehouse_id'],workspace.warehouse_id)
ASOF        = $(call lab_value,['data']['as_of'],data.as_of)
MODEL_AGENT = $(call lab_value,['models']['agent'],models.agent)
# Optional agent.max_steps in lab.yaml. 20 when the key is missing.
MAX_STEPS   = $(or $(shell $(PY) -c "import yaml;print((yaml.safe_load(open('lab.yaml')).get('agent') or {}).get('max_steps') or 20)" 2>/dev/null),20)
EXP         = $(call state_value,experiment_id,run make tracing first)
TRACE       = $(call state_value,trace_schema,run make tracing first)
AGENTVARS   = --var=experiment_id=$(EXP) --var=warehouse_id=$(WH) --var=trace_schema=$(TRACE) --var=agent_model=$(MODEL_AGENT) --var=max_steps=$(MAX_STEPS)
REPLACE_FLAG = $(if $(filter 1,$(CONFIRM_REPLACE)),--replace)

LABEL   ?= v1
BENCHMARK ?= eval/benchmark.yaml
NOTES   ?=
SERIES  ?=
SAMPLES ?= 3
FROM    ?= feedback
N       ?=
CONFIRM ?=
CONFIRM_REPLACE ?=

.PHONY: setup workbench tracing data agents scope agent ablation-agent ablation-agent-destroy supervisors overlap \
	gold eval regrade direct verify-scope traces verify-direct load agreement gateway report app test lint teardown teardown-all

setup:            ## lab.yaml from the example if missing, and Python environments: root, custom_agent, app/backend
	@test -f lab.yaml || { cp lab.example.yaml lab.yaml; echo "Created lab.yaml from lab.example.yaml. Edit the workspace values in it before the next step."; }
	uv sync --python 3.12
	cd custom_agent && uv sync --python 3.12
	cd app/backend && uv sync

workbench:        ## Genie Workbench app that builds the Genie Agents (manual prerequisite, scripted, not yet run end to end)
	bash scripts/setup_workbench.sh

tracing:          ## MLflow experiment with traces stored in Unity Catalog. Creates the lab schema
	$(PY) scripts/setup_tracing.py

data:             ## Schemas, tables, synthetic data, metric views, dashboard. Stops if tables exist (CONFIRM_REPLACE=1 rebuilds)
	$(PY) data_model/build_ddl.py --root . --skip-metric-views $(REPLACE_FLAG)
	databricks bundle deploy --profile $(PROFILE) --var=as_of=$(ASOF)
	databricks bundle run hoshi_generate_data --profile $(PROFILE) --var=as_of=$(ASOF)
	$(PY) data_model/build_ddl.py --root . --metric-views-only
	$(PY) data_model/deploy_dashboard.py

agents:           ## Two curated Genie Agents, created through the Genie Workbench app
	$(PY) genie/create_agents.py

scope:            ## Genie One scope for arm A: skill and workspace instructions
	$(PY) genie_one_scope/publish.py

agent:            ## Fallback agent for arm B (bundle target dev): context, app, grants
	$(PY) scripts/sync_context.py
	cd custom_agent && databricks bundle deploy -t dev --profile $(PROFILE) $(AGENTVARS)
	cd custom_agent && databricks bundle run -t dev --profile $(PROFILE) $(AGENTVARS) hoshi_fallback_agent
	$(PY) scripts/grants.py agent

ablation-agent:   ## Ablation build of the fallback agent (bundle target ablation)
	cd custom_agent && databricks bundle deploy -t ablation --profile $(PROFILE) $(AGENTVARS)
	cd custom_agent && databricks bundle run -t ablation --profile $(PROFILE) $(AGENTVARS) hoshi_fallback_agent
	$(PY) scripts/grants.py ablation

ablation-agent-destroy: ## Remove the ablation build of the fallback agent
	cd custom_agent && databricks bundle destroy -t ablation --auto-approve --profile $(PROFILE) $(AGENTVARS)

supervisors:      ## Supervisor A (Genie One) and Supervisor B (custom agent)
	$(PY) supervisors/create.py

overlap:          ## Fail if a benchmark question matches an example the agents were given
	$(PY) scripts/check_overlap.py

gold:             ## Draft benchmark questions with reference SQL from a larger model: make gold FROM=feedback | context | my_questions.txt
	PYTHONUNBUFFERED=1 $(PY) eval/build_benchmark.py --from $(FROM) $(if $(N),--n $(N))

eval:             ## Benchmark both supervisors: make eval LABEL=v1 NOTES="first run" (hard set: BENCHMARK=eval/benchmark_hard.yaml, one series: SERIES=...)
	PYTHONUNBUFFERED=1 $(PY) eval/run_eval.py --benchmark $(BENCHMARK) --label $(LABEL) --notes "$(NOTES)" $(if $(SERIES),--series $(SERIES))

regrade:          ## Grade a saved run again without asking the supervisors again: make regrade LABEL=v1
	$(PY) eval/run_eval.py --label $(LABEL) --regrade

direct:           ## Send out-of-scope requests straight to each fallback, without the supervisor: make direct SAMPLES=3
	PYTHONUNBUFFERED=1 $(PY) eval/redteam.py --samples $(SAMPLES)

verify-scope:     ## Check in query history what each arm really ran: make verify-scope LABEL=v1
	$(PY) eval/verify_scope.py --label $(LABEL)

traces:           ## Save what the supervisor traces say each agent ran, with the Genie Agents' SQL: make traces LABEL=v1
	$(PY) eval/export_traces.py --label $(LABEL)

verify-direct:    ## The same check for the last direct test
	$(PY) eval/verify_scope.py --direct latest

load:             ## Response time and errors with 1, 4 and 12 requests at once
	PYTHONUNBUFFERED=1 $(PY) eval/load_test.py

agreement:        ## Second judge model and human review sheet for a sample of a run: make agreement LABEL=v1
	$(PY) eval/judge_agreement.py --label $(LABEL)

gateway:          ## Copy Unity Gateway usage for a run into the lab schema (usage lags by about an hour)
	$(PY) eval/snapshot_gateway.py --label $(LABEL)

report:           ## Summary of the saved runs
	$(PY) eval/report.py

app:              ## Lab UI: build frontend, deploy app, grants, chat tables
	cd app/frontend && npm install && npm run build
	$(PY) scripts/render_app_config.py
	cd app && databricks bundle deploy --profile $(PROFILE) --var warehouse_id=$(WH)
	cd app && databricks bundle run --profile $(PROFILE) --var warehouse_id=$(WH) hoshi_fallback_lab
	$(PY) scripts/grants.py ui
	$(PY) scripts/setup_chat.py

test:             ## Unit tests: root, custom_agent, app/backend
	$(PY) -m pytest -q
	cd custom_agent && .venv/bin/python -m pytest -q
	cd app/backend && .venv/bin/python -m pytest -q

lint:             ## ruff check and format check: root, custom_agent, app/backend
	.venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd custom_agent && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd app/backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

teardown:         ## Remove the Genie One skill and the lab's part of the workspace instructions file
	$(PY) scripts/teardown.py --what scope

teardown-all:     ## Remove everything the lab created in the workspace. Needs CONFIRM=1. Keeps schemas (see docs/REPLICATE.md)
	@test "$(CONFIRM)" = 1 || { echo "Refusing to delete without CONFIRM=1. First read the plan: $(PY) scripts/teardown.py --what all --dry-run"; exit 1; }
	$(PY) scripts/teardown.py --what all --yes
