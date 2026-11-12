# Supervisor fallback lab

A lab you can run in your own Databricks workspace to answer one question with evidence:

> A Supervisor Agent routes questions to curated Genie Agents. What should answer the questions those
> agents cannot, and how well can you control what it reads?

The lab builds two supervisors over the same data and the same two curated Genie Agents. Each gets a
different fallback. It then asks both the same questions, written the way people really ask them, and
measures accuracy, routing, scope, speed and cost.

| | Supervisor A | Supervisor B |
|---|---|---|
| Curated agents | Subscribers and Revenue, Content and Viewing | the same two |
| Fallback | Genie One, through its managed MCP server | A custom text-to-SQL agent, deployed as a Databricks App |
| How its scope is controlled | Text only: a Genie One skill, workspace instructions and a scope line from the supervisor | In code: a SQL guard rejects any table that is not on the allowlist |
| Runs SQL as | The calling user | The calling user |

Everything runs on synthetic data for a fictional anime streaming company, Hoshi Stream. No real
customer data is involved. You change one file, `lab.yaml`, and run `make` targets in order.

This is a lab, not a product. It is not an official Databricks offering and comes with no support.
Several features it uses are in preview, and the Supervisor Agent product is marked legacy in the
Databricks docs. Read [Limits](#limits) before you rely on any number.

## Contents

- [What the reference run found](#what-the-reference-run-found)
- [How it works](#how-it-works)
- [What you need](#what-you-need)
- [Set it up in your workspace](#set-it-up-in-your-workspace)
- [Run the experiment](#run-the-experiment)
- [Look at the results](#look-at-the-results)
- [Change the experiment](#change-the-experiment)
- [Use your own data](#use-your-own-data)
- [Remove everything](#remove-everything)
- [If something goes wrong](#if-something-goes-wrong)
- [Limits](#limits)
- [What is in the repo](#what-is-in-the-repo)
- [Licence and notices](#licence-and-notices)

## What the reference run found

These numbers come from one workspace in November 2026. Your run will differ. The full write-up,
with every table and the limits of each claim, is in [docs/RESULTS.md](docs/RESULTS.md). The raw
answers and every grading are in `eval/results/`.

On 48 questions the agents had never seen, asked three times:

| | A: Genie One | B: custom agent |
|---|---|---|
| Turns passed (three repeats) | 83%, 73%, 75% | 79%, 77%, 79% |
| Sent to the right agent | 84% to 93% | 93% to 98% |
| Middle response time | 26 to 28 s | 24 to 25 s |
| Slowest one turn in twenty | 54 to 62 s | 32 to 35 s |
| Statements outside the agreed scope, in query history, over 8 runs | 2 of 1,911 | 0 |
| Out-of-scope requests sent straight to the fallback that it handled acceptably | 33 of 33 with the scope line, 24 of 33 without | 33 of 33 |

In plain words:

- **Accuracy does not separate the two.** The difference is smaller than the change from one repeat
  to the next.
- **Genie One kept to the scope when the supervisor sent the scope line.** Without the line it
  answered questions about other data the user could read. It never read the off-limits data.
- **The custom agent kept to the scope in every test.** It did so even with its table allowlist
  turned off, so in this lab the allowlist is a second barrier that was never needed.
- **The supervisors differed most in routing**, which comes from how the fallback tool is described
  to the supervisor.
- **Cost is visible per request for the custom agent only.** Genie One reports calls and no tokens.
- **Genie One also looks beyond tables.** On every question it listed the tools of six connected
  services of the person asking, such as Slack and Gmail. It never called one.

## How it works

```mermaid
flowchart LR
  user([Person asking]) --> ui[Lab UI<br/>Databricks App]
  ui --> supA[Supervisor A]
  ui --> supB[Supervisor B]
  supA --> g1[Genie Agent<br/>Subscribers and Revenue]
  supA --> g2[Genie Agent<br/>Content and Viewing]
  supB --> g1
  supB --> g2
  supA -- "scope line" --> genieone[Genie One<br/>managed MCP]
  supB -- "user token" --> agent[Custom agent<br/>Databricks App, MCP]
  agent --> guard{SQL guard<br/>table allowlist}
  guard --> dbsql[SQL through Unity Gateway]
  genieone --> data[(Unity Catalog<br/>synthetic data)]
  dbsql --> data
  g1 --> data
  g2 --> data
  runner[Benchmark runner<br/>and MLflow judges] --> supA
  runner --> supB
  runner --> results[(Delta tables<br/>and result files)]
  ui --> results
```

- **Data.** Eight schemas of synthetic data built from the `media_broadcasting` model in the
  Databricks industry data models. Four belong to the curated agents, three to the fallback, and one
  (`talent`) is off limits to every agent.
- **Arm A.** Genie One has no setting that limits it to chosen tables. The lab steers it with a skill,
  a section in the workspace instructions file, and a scope line the supervisor sends with every call.
- **Arm B.** The custom agent reads a folder of table descriptions generated from Unity Catalog,
  writes SQL, and passes every statement through a guard built on sqlglot. The guard allows one
  read-only query over allowlisted tables. The model and the SQL both go through Unity Gateway.
- **Evaluation.** Each question has an expected route, an expected behaviour and reference SQL that
  is run at grading time. MLflow judges decide whether the answer agrees with the reference result,
  what kind of response it was and whether a refusal leaked anything. Code checks decide routing and
  scope. A turn passes only when all of these hold.

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the full diagram, the identities involved, and the
checks the evaluation runs on itself.

## What you need

**In the workspace**

| Need | Used for |
|---|---|
| Unity Catalog, and a catalog where you can create schemas | The synthetic data and the lab tables |
| A serverless SQL warehouse you can use | All SQL |
| Genie, with Genie One and its managed MCP server (`system.ai.genie_one_mcp`) | Arm A |
| Agent Bricks Supervisor Agents | Both supervisors |
| Databricks Apps with user authorization turned on | The custom agent, the UI and the Genie Workbench |
| Unity Gateway with `system.ai.dbsql` and one `system.ai` model service | Arm B |
| Two more model serving endpoints for the judges | Grading |
| Permission to write `/Workspace/.genie_workspace_instructions.md` (usually a workspace admin) | Arm A. The lab adds one marked section and keeps the rest |
| Read access to `system.query.history` and `system.ai_gateway.usage` | Optional. The query history check and the cost view |
| The `samples` catalog | Optional. The direct test asks about two of its tables |

Model names are set in `lab.yaml`. If your workspace has other models, change them there. Keep the
judge in a different model family from the agent.

**On your machine**

- Databricks CLI 1.25 or later, signed in with a profile for the workspace
- [`uv`](https://docs.astral.sh/uv/), which installs Python 3.12 for you
- Node 20.19 or later and `npm`, for the UI build
- `git` and `make`

**What it costs.** The lab uses serverless SQL, three small apps, two supervisor endpoints and model
calls for the agents and the judges. One full benchmark run asks between 100 and 150 questions and
makes a few hundred judge calls. Remove the lab when you are done
([Remove everything](#remove-everything)).

## Set it up in your workspace

Run the steps in this order. Each one can be run again. The table after the steps says what each
step creates or changes.

**1. Get the code and sign in**

```bash
git clone https://github.com/Praneeth16/supervisor-fallback-lab.git
cd supervisor-fallback-lab
databricks auth login --host https://<your-workspace-host> --profile <your-profile>
```

**2. Create your configuration**

```bash
make setup
```

This creates `lab.yaml` from `lab.example.yaml` and three Python environments. Open `lab.yaml` and
set the four workspace values:

```yaml
workspace:
  profile: <your-profile>
  host: https://<your-workspace-host>
  warehouse_id: <id of a serverless SQL warehouse>
  catalog: <a catalog where you can create schemas>
  schema_prefix: hoshi_
```

Leave the rest as it is for a first run. `lab.yaml` stays on your machine and is not in git.

**3. Deploy the Genie Workbench**

```bash
make workbench
```

The lab builds its two Genie Agents through the
[Genie Workbench](https://github.com/databricks-solutions/databricks-genie-workbench), which is a
separate app. This step clones it at a pinned commit, deploys it and adds one permission scope the
lab needs. The script was written from a manual deploy and has not been run from start to finish on
a clean workspace. If it stops, follow "The Genie Workbench step" in
[docs/REPLICATE.md](docs/REPLICATE.md) by hand.

**4. Create the data**

```bash
make tracing
make data
```

`make tracing` creates the lab schema and an MLflow experiment whose traces are stored in Unity
Catalog. `make data` creates the schemas and tables, fills them with seeded synthetic data, and
creates two metric views and a dashboard. `make data` stops if lab tables already exist, so it never
overwrites data by accident.

**5. Build the agents**

```bash
make agents        # the two curated Genie Agents
make scope         # Genie One skill and workspace instructions for arm A
make agent         # the custom fallback agent for arm B
make supervisors   # both supervisors
```

A new supervisor endpoint can take about ten minutes before it answers.

`make scope` changes a file that every Genie One user in the workspace shares. It backs the file up
to `genie_one_scope/backup/`, adds or replaces only its own marked section, and leaves everything
else alone.

**6. Deploy the UI**

```bash
make app
```

This installs the frontend packages from the public npm registry, builds the UI and deploys it. The
command prints the URL of the lab UI. Open it and ask both supervisors a question on the Ask page to
check that everything is connected.

### What each step creates

| Step | Creates or changes | Safe to run again |
|---|---|---|
| `make setup` | `lab.yaml` and local Python environments | Yes |
| `make workbench` | The Genie Workbench app | Yes |
| `make tracing` | Schema `<catalog>.<prefix>lab`, an MLflow experiment | Yes |
| `make data` | Eight data schemas, 31 tables, two metric views, one dashboard, one job | Only when no lab table exists. `CONFIRM_REPLACE=1` rebuilds and drops the data |
| `make agents` | Two Genie Agents | Yes |
| `make scope` | A Genie One skill, and one marked section in the shared workspace instructions file | Yes. The file is backed up first |
| `make agent` | The custom agent app, and read grants for its service principal on the in-scope schemas | Yes |
| `make supervisors` | Two Supervisor Agents and their serving endpoints | Yes |
| `make app` | The lab UI app, and read grants on the lab schema | Yes |

The ids of what was created are kept in `state.json` on your machine.

## Run the experiment

```bash
make overlap
make eval LABEL=run1 SERIES=run1 BENCHMARK=eval/benchmark_holdout.yaml NOTES="first run"
make verify-scope LABEL=run1
make traces LABEL=run1
make agreement LABEL=run1
make direct SAMPLES=3
make verify-direct
make load
make gateway LABEL=run1      # about an hour after the run
make report
```

| Command | What it does | About how long |
|---|---|---|
| `make overlap` | Fails if a benchmark question matches an example the agents were given | Seconds |
| `make eval` | Asks every question through both supervisors, then grades the answers | 10 minutes of asking and 20 of grading for each supervisor |
| `make verify-scope` | Reads query history and lists every statement the agents ran during the run | A minute. Wait ten minutes after the run, because query history trails |
| `make traces` | Reads the supervisor's trace of every turn and saves which tools were called and the SQL each ran, including the SQL of the curated Genie Agents | 5 minutes |
| `make agreement` | Has a second judge model re-judge 30 turns and writes a sheet for a person to label | A few minutes |
| `make direct` | Sends out-of-scope requests straight to each fallback, three times each, with one in-scope control | 10 minutes |
| `make verify-direct` | The query history check for the direct test | A minute |
| `make load` | Sends questions with 1, 4 and 12 requests in flight at once | 15 minutes |
| `make gateway` | Copies the Unity Gateway usage of the run into the lab schema | A minute |
| `make report` | Writes the numbers of all runs into `docs/RESULTS.md` | A minute |

There are three question sets:

| File | Turns | Use |
|---|---|---|
| `eval/benchmark_holdout.yaml` | 48 | Written without sight of the agents' instructions. Report this one. Do not tune on it |
| `eval/benchmark.yaml` | 74 | The first set. The agents were tuned while looking at its failures |
| `eval/benchmark_hard.yaml` | 66 | Harder questions, also seen during tuning |

Three things to know before you run:

- **Use a new `LABEL` for every run.** Answers are saved once and never overwritten.
- **Repeat a setup to see the noise.** Run it again with a new label and the same `SERIES`. The
  report then shows the range.
- **Do not use Genie or the SQL MCP server for other work while a run is in progress.** The query
  history check cannot tell your own statements from the agents'.

To include the custom agent without its table allowlist in the direct test, run `make ablation-agent`
before `make direct` and `make ablation-agent-destroy` after it.

`eval/results/` and `docs/RESULTS.md` come with the reference run in them. `make report` reads your
workspace, so after your first run the tables in `docs/RESULTS.md` show your runs. The text above
the tables still describes the reference run until you rewrite it.

## Look at the results

- **The UI.** The Benchmark page shows scores for each supervisor, by category and by question, with
  the judges' reasons and every grading of a run. The Governance page shows the scope, tables touched
  outside it, the direct test, what query history says really ran, and Unity Gateway usage.
- **`docs/RESULTS.md`.** `make report` rewrites the tables between the two marker lines and keeps
  the text around them.
- **`eval/results/<label>/`.** What each supervisor said (`*.answers.json`) and every grading of it
  (`*.grading-<n>.json`).
- **MLflow.** One run for each grading, with the judges' feedback on every question.

![Governance page: the direct test and what query history shows](app/screenshots/11-governance-v3-hard.png)

![Benchmark page: every grading of a run is kept](app/screenshots/12-benchmark-holdout-grading-history.png)

## Change the experiment

Change one thing, publish it to the workspace, and run the benchmark again under a new label.

| To change | Edit | Then run |
|---|---|---|
| Routing rules and tool descriptions | `supervisors/instructions_*.md`, `supervisors/create.py` | `make supervisors` |
| What Genie One is told about the scope | `lab.yaml` (scope lists), `genie_one_scope/publish.py` | `make scope` |
| The custom agent's rules or guard | `custom_agent/agent_server/` | `make agent` |
| A curated Genie Agent | `genie/*.yaml` | `make agents` |
| Which schemas are in scope | `lab.yaml` (scope lists) | `make scope agent supervisors` |
| The judges | `eval/judges.py`, and raise `JUDGES_VERSION` | `make regrade LABEL=<label>` |

When the judges or the scoring rules change, grade the saved answers again with `make regrade`. The
earlier grading is kept next to the new one. Write new holdout questions after you change an agent
because of a holdout failure, because that set is then no longer unseen.

## Use your own data

The lab is built around the synthetic Hoshi Stream data, and that is the supported way to run it. To
point it at your own tables you need to replace these parts yourself:

1. Skip `make data`. List your schemas in the `scope` section of `lab.yaml`. Schema names follow
   `<schema_prefix><domain>`.
2. Write a spec for each curated Genie Agent in `genie/`, or point `supervisors/create.py` at Genie
   Agents you already have.
3. Write your own questions with reference SQL in a new file under `eval/`, in the same format as
   `eval/benchmark_holdout.yaml`. Have someone who has not seen the agents' instructions write them.
4. Run `make scope agent supervisors`, then the experiment.

Start with the synthetic data so you know what a working run looks like.

## Remove everything

```bash
make teardown                  # only the Genie One skill and the lab's section of the shared instructions file
.venv/bin/python scripts/teardown.py --what all --dry-run    # prints what would be removed
make teardown-all CONFIRM=1    # removes the supervisors, apps, Genie Agents, dashboard, experiments and job
```

`make teardown-all` keeps the data schemas. To drop them as well, and to remove the Genie Workbench
app, run `scripts/teardown.py` with `--drop-data` and `--include-workbench`. Read the printed plan
first. The teardown script has been checked with `--dry-run` only.

## If something goes wrong

| What you see | Why | What to do |
|---|---|---|
| `lab.yaml ... is empty or lab.yaml is missing` | No configuration yet | `make setup`, then edit `lab.yaml` |
| `make data` stops because tables already exist | It never overwrites data | Nothing, or `make data CONFIRM_REPLACE=1` to rebuild |
| A supervisor returns an error right after `make supervisors` | The endpoint is still starting | Wait about ten minutes |
| "Failed to register tools from Databricks App MCP server" | The supervisor needs the app to serve MCP at `/mcp` | Redeploy with `make agent` and check that the app is running |
| The custom agent says it has no user token | User authorization is off for Databricks Apps | Turn it on in the workspace, then `make agent` |
| A deploy says "deploy lock acquired" and nothing else is deploying | An earlier deploy was interrupted | Run the same `databricks bundle deploy` with `--force-lock` |
| `OS keyring unreachable` during grading | Too many lab processes are asking the CLI for a token at once | Run one evaluation at a time. The step retries by itself |
| `make verify-scope` finds no statements | Query history trails by several minutes | Run it again later |
| `make gateway` finds no usage | The usage table trails by about an hour | Run it again later. The stored copy is kept |
| Genie One ignores the scope | The supervisor rewrote the question and dropped the scope line | Check `supervisors/instructions_a.md` and run `make supervisors` |

More findings from building the lab are in [docs/SPIKES.md](docs/SPIKES.md) and at the end of
[docs/REPLICATE.md](docs/REPLICATE.md).

## Limits

- **Small scale.** Two curated agents and one person asking. The lab does not show how routing
  behaves with many agents whose areas overlap, with row filters and column masks for different
  people, or under sustained load.
- **Judges are language models.** A second judge model re-judges a sample and a review sheet is
  written for a person. Until a person fills that sheet in, no human has checked the judges.
- **The holdout set stays a holdout only while nobody tunes on it.**
- **Synthetic data.** It is consistent and not realistic in every respect. `docs/DATA.md` lists the
  traps, for example that ad revenue is very small.
- **Not run from nothing yet.** Every step was run in the reference workspace while the lab was
  built. The whole sequence has not been run from start to finish on a clean workspace, and the
  Genie Workbench and teardown scripts have not been run end to end.
- **Preview and legacy features.** Genie One over MCP, Unity Gateway and Supervisor Agents may change.
  The custom agent is a standalone app with an MCP endpoint, so it can be attached to another
  orchestrator.
- **The Genie One skill is installed for the person who runs `make scope`.** Other users get the
  workspace instructions only.

## What is in the repo

```
lab.example.yaml     copy to lab.yaml: workspace, models, as-of date, scope lists
Makefile             the steps, in order
data_model/          table subset of the industry model, synthetic data job, metric views, dashboard
genie/               the two Genie Agent specs and the script that creates them through Genie Workbench
genie_one_scope/     renders and publishes the Genie One skill and workspace instructions (arm A)
custom_agent/        the fallback agent (arm B): SQL guard, MCP endpoint, bundle
supervisors/         instructions and the script that creates both supervisors
eval/                three question sets with reference SQL, MLflow judges, scoring, runner,
                     direct test, query history check, judge check, load test, report
eval/results/        answers and gradings of the reference run
app/                 the lab UI: FastAPI backend, React frontend built with appkit-ui
scripts/             shared config, grants, tracing setup, overlap check, teardown
docs/                REPLICATE.md, ARCHITECTURE.md, RESULTS.md, DATA.md, SPIKES.md, CONTRACT.md
```

`make test` runs the unit tests of all three Python projects. `make lint` runs ruff.

## Licence and notices

This repo is under the Databricks License. See [LICENSE](LICENSE). [NOTICE.md](NOTICE.md) says where
code, data model names and ideas came from.

The workspace host, workspace id and user name in `eval/results/` were replaced with placeholders.
Nothing else in those files was changed.
