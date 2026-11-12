# How to run the lab

Everything is driven by `lab.yaml` and the `Makefile`. Run the steps below in this order. The
workspace objects the steps create are recorded in `state.json`, which stays on your machine and is
not in git.

Some steps replace or delete things in the workspace. The table at the end of this page lists them.
Read it before you run a step for the first time.

## What you need

In the workspace:

- Unity Catalog, a serverless SQL warehouse, and a catalog where you can create schemas.
- Genie. Agent Bricks Supervisor Agents (Beta). The Databricks docs mark the Supervisor Agent product as
  legacy.
- Databricks Apps, with user authorization (on-behalf-of-user) turned on.
- Unity Gateway and the managed MCP servers, both in preview. The lab calls `system.ai.genie_one_mcp`,
  `system.ai.dbsql` and one `system.ai` model service.
- The `samples` catalog. The direct test (`make direct`) asks questions about two of its tables.
- Account-level read access to the system tables `system.ai_gateway.usage` and `system.query.history`.
  The scope check and the gateway step read them.

On your machine:

- Databricks CLI 1.25 or later, with a profile for the workspace. The `experimental aitools` command must be
  there.
- `uv`. It installs Python 3.12 for you.
- Node 20.19 or later, for the frontend build and the Genie Workbench.
- `git`, for the Genie Workbench clone.

## Steps

1. **Configure.** Edit `lab.yaml`: profile, host, warehouse, catalog, schema prefix, brand, models, the
   as-of date of the data and the scope lists. Then run `make setup`. It creates three Python environments:
   the root one for the lab scripts and tests, one for `custom_agent` and one for `app/backend`.

2. **Genie Workbench.** Run `make workbench`. The Workbench is a separate app that builds the two Genie
   Agents. It is a manual prerequisite. The script clones the Workbench at a pinned commit into `.vendor/`,
   writes its `.env.deploy` from `lab.yaml`, deploys it and adds the `genie` user scope the lab needs. It then
   saves `workbench_app` and `workbench_url` in `state.json`. See the section below.

3. **Tracing.** `make tracing` creates the lab schema (`<catalog>.<prefix>lab`) if it is missing. It then
   creates the MLflow experiment and stores its traces in tables in that schema, so the traces can be queried
   with SQL.

4. **Data.** `make data` creates the schemas and tables from the `media_broadcasting` industry model, fills
   them with seeded synthetic data, and creates two metric views and one dashboard. It also writes one row to
   `<catalog>.<prefix>lab.data_manifest`. That row records the as-of date, the seed, the model commit, the
   table count and the row count, so you can tell which data a run used. The model is downloaded at a pinned
   commit and is not stored in this repo. To change which tables and columns are used, edit
   `data_model/model_subset.yaml`. `docs/DATA.md` describes the data.

5. **Genie Agents.** `make agents` builds the two curated Genie Agents from `genie/*.yaml` through the
   Workbench and runs its IQ scan on each.

6. **Genie One scope (arm A).** `make scope` renders the scope from `lab.yaml` into a Genie One skill. It
   also merges the lab section into the shared workspace instructions file, `/Workspace/.genie_workspace_instructions.md`.
   Genie One reads that file for every user who can view it. The file already has content from other people,
   so the step backs it up and merges the lab section in. It does not overwrite the file.

7. **Fallback agent (arm B).** `make agent` writes the agent's context folder from Unity Catalog, deploys the
   fallback agent app through its bundle and grants its service principal read access to the in-scope schemas
   only. `make ablation-agent` deploys a second build of the same agent, for experiments. `make ablation-agent-destroy`
   removes it.

8. **Supervisors.** `make supervisors` creates both supervisors with the same Genie Agents and routing rules.
   They differ only in the fallback tool.

9. **Overlap.** `make overlap` compares every benchmark question and its reference SQL with the examples the
   Genie Agents and the supervisors were given. It fails when one matches. An agent that has seen a question
   is not being tested on it.

10. **Benchmark.** `make eval LABEL=v1 NOTES="first run"` asks every question in `eval/benchmark.yaml` through
    both supervisors, grades the answers, and writes the results under the label. Asking takes about ten
    minutes for each supervisor and grading about twenty. Use a new label for every run. Answers are saved
    once and are never overwritten. `make regrade LABEL=v1` grades the saved answers again and keeps the
    earlier grading next to the new one. When only one judge changed, ask only that judge again:
    `.venv/bin/python eval/run_eval.py --label v1 --regrade --rejudge leaked`. Each grading records the
    scoring version and the revision of the judge instructions, for example `2.1`.

    There are three question sets. Choose one with `BENCHMARK=`:

    | File | Use |
    |---|---|
    | `eval/benchmark.yaml` | The first set. The agents were tuned while looking at its failures. |
    | `eval/benchmark_hard.yaml` | Harder questions. Also seen during tuning. |
    | `eval/benchmark_holdout.yaml` | Written without sight of the agents' instructions. Do not tune on it. Report this one. |

    To repeat a setup, run it several times with different labels and one series name, for example
    `make eval LABEL=v3-holdout-r2 SERIES=v3-holdout BENCHMARK=eval/benchmark_holdout.yaml`.

11. **Direct test.** `make direct SAMPLES=3` sends out-of-scope requests straight to each fallback, without the
    supervisor in front, three times each. One request is an in-scope control that should be answered. To
    include the custom agent without its table allowlist, run `make ablation-agent` first and
    `make ablation-agent-destroy` afterwards. Then run `make verify-direct`.

    `make load` sends fallback questions with 1, 4 and 12 requests in flight at once and records the response
    time and errors.

12. **Scope check.** `make verify-scope LABEL=v1` reads `system.query.history` and lists every statement the
    Genie Agents, Genie One and the SQL MCP server ran during each arm of the run. Do not use Genie or the SQL
    MCP server for other work while a run is in progress, because the check cannot tell those statements apart.

    `make traces LABEL=v1` reads the supervisor's trace of every turn and saves which tools were called and
    the SQL each one ran, in `eval/results/v1/<arm>.trace-summary.json`. This is where the SQL of the curated
    Genie Agents can be read for each question. The supervisor's reply does not show it.

13. **Judge check.** `make agreement LABEL=v1` asks a second judge model about a sample of 30 turns and writes
    `eval/results/v1/human_review.csv`. Have a person fill in the sheet, then run the command again. It then
    shows how far the two judge models and the person agree.

14. **Gateway usage.** About an hour after a run, `make gateway LABEL=v1` copies the Unity Gateway usage of
    that run into the lab schema. The usage table lags by about an hour, so run this step later. If no usage is
    found yet, the stored copy is kept.

15. **Report.** `make report` writes the numbers of all runs into `docs/RESULTS.md`, between the two marker
    lines. Text outside the markers is kept.

16. **UI.** `make app` builds the frontend, deploys the lab app and grants it read access to the lab schema.

To compare two versions, change the instructions, the skill, the tool descriptions or the agent rules. Then
rerun the step that publishes them and run `make eval` with a new label, for example `make eval LABEL=v2 NOTES="what changed"`.

Run `make test` for the unit tests and `make lint` for ruff. Both cover the root project and the two
subprojects.

## The Genie Workbench step

The Workbench is a separate project: <https://github.com/databricks-solutions/databricks-genie-workbench>.
`scripts/setup_workbench.sh` does the steps below. They come from a manual deploy on 2026-11-11, and the
script has not been run end to end yet.

1. Clone the pinned commit into `.vendor/databricks-genie-workbench`, which git ignores.
2. Write `.env.deploy` from `lab.yaml`: the warehouse, the catalog, the app name `genie-workbench-hoshi`, the
   profile and the gateway route.
3. Run the Workbench's `scripts/deploy.sh`. Use `--update` when the app already exists.
4. Add the `genie` user scope to the app. `deploy.sh` sets the scopes again on every run without `genie`, so
   the script adds it after the deploy. Without this scope the Workbench cannot list or create Genie Agents
   when it is called with a user token. The script updates the app with its name, resources and scopes, stops
   and starts it, and deploys it again from the same source folder.
5. Save `workbench_app` and `workbench_url` in `state.json`.

`genie/WORKBENCH_API.md` documents the endpoints this lab uses.

## What each step replaces or changes

| Step | What it changes | Can you run it again? |
|---|---|---|
| `make tracing` | Creates the lab schema and the MLflow experiment | Yes. Nothing is replaced. |
| `make data` | Creates the schemas, tables and metric views. Then the generator overwrites every table with new rows. Deploys the dashboard. | Only when no lab table exists. If tables exist, the step stops and changes nothing. To rebuild, run `make data CONFIRM_REPLACE=1`. That drops the data in every lab table. |
| `make scope` | Writes the Genie One skill, and merges the lab section into the shared workspace instructions file (`/Workspace/.genie_workspace_instructions.md`). Other people may read that file. | Yes. The file is backed up first. The backup is in `genie_one_scope/backup/`, which git ignores, because it may hold someone else's instructions. |
| `make agent` | Rewrites the context folder, redeploys the fallback agent app and grants it access | Yes |
| `make supervisors` | Updates the instructions, tools and examples of both supervisors. They are matched by name. | Yes |
| `make eval` | Writes a new run under its label | Yes, but use a new label for each run you want to keep |
| `make app` | Redeploys the lab UI app | Yes |
| `make workbench` | Redeploys the Workbench app and restarts it to apply the scope | Yes |
| `make teardown` | Removes the Genie One skill and the lab section of the workspace instructions file | Yes |
| `make teardown-all CONFIRM=1` | Removes what the lab created. See the next section. | No. The objects are gone. |

## What teardown removes

`make teardown` removes only the Genie One skill and the lab's part of the shared workspace instructions file.

`make teardown-all CONFIRM=1` removes:

- the two supervisors
- the Genie One skill and the lab's part of the workspace instructions file
- the fallback agent app and the lab UI app (through their bundles), and the ablation app if it was deployed
- the two Genie Agents and the dashboard. They go to the workspace trash.
- the MLflow experiments of the lab and of the two supervisors
- the data job bundle

Read the plan before you confirm. It is printed first:

```
.venv/bin/python scripts/teardown.py --what all --dry-run
```

Two options are not part of `make teardown-all`. Run the script directly for them:

- `--include-workbench` also removes the Genie Workbench app.
- `--drop-data` also drops every lab schema and all its tables, which are the schemas whose names start with the schema prefix.

Teardown leaves the catalog, the warehouse, the `samples` catalog and any schema that is not the lab's.

## When the as-of date changes

The synthetic data runs up to the day before `data.as_of` in `lab.yaml`. Every agent treats that date as today. So
when you change the date, the data, the agents and the benchmark answers all change. Old results are not
comparable with new ones. Run these steps in order:

1. Change `data.as_of` in `lab.yaml`.
2. `make data CONFIRM_REPLACE=1`
3. `make agents`
4. `make scope`
5. `make agent`
6. `make supervisors`
7. `make eval LABEL=<a new label>`

Do not compare the new run with runs that used the old date. Their reference answers came from the old data.
The gold results of the old runs stay in their own labels.

## Things that behave differently from what you might expect

These were found while building the lab. `docs/SPIKES.md` has the details.

- Attach Genie One to a supervisor through the REST API with a `uc_mcp` tool. The CLI drops that field.
- A custom agent app must serve MCP at `/mcp`. The supervisor does not call a plain Responses API app.
- The supervisor asks the caller to approve each call to an app tool. `labcore/supervisor.py`
  approves automatically; the UI and the benchmark both use it.
- The supervisor rewrites questions before it delegates. Scope rules that depend on certain words
  reaching Genie One will be skipped unless the supervisor is told to send them.
- Skill tools on supervisors are a workspace preview. Without it, `make supervisors` skips the skill
  tool and the scope still reaches Genie One through the supervisor instructions, the Genie One
  skill and the workspace instructions.
- An app must set `MLFLOW_TRACING_DESTINATION` to the lab schema. Linking the experiment to Unity
  Catalog is not enough; without the variable, traces go to experiment storage, which apps cannot reach.
- With the Unity Gateway model endpoint, use the Responses API. With Chat Completions the model's
  reasoning blocks break the OpenAI Agents SDK.
- `system.ai.dbsql` returns rows in two shapes (`data_typed_array` and `data_array`). The agent reads both.
- The synthetic data ends the day before `data.as_of`. Every agent is told to treat that date as
  today. When you regenerate the data, follow the as-of procedure above.
