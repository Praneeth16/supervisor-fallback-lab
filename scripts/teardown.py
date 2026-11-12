"""Remove what the lab created in the workspace. The ids come from state.json.

  python scripts/teardown.py                        # scope only: Genie One skill and workspace instructions
  python scripts/teardown.py --what all --dry-run   # print the plan for --what all, change nothing
  python scripts/teardown.py --what all --yes       # carry out the plan

--what all removes the two supervisors, the Genie One scope, the lab apps (through their bundles), the two
Genie Agents, the dashboard, the MLflow experiments and the data job. Genie Agents and the dashboard go to
the workspace trash. The Genie Workbench app stays unless --include-workbench is passed. The lab schemas stay
unless --drop-data is passed.
"""

import argparse
import functools
import subprocess
import sys

from labconfig import ROOT, load_config, load_state, sql

WORKBENCH = ROOT / ".vendor" / "databricks-genie-workbench"
run = functools.partial(subprocess.run, check=True)


def dbx(*args: str, profile: str) -> list[str]:
    return ["databricks", *args, "--profile", profile]


def destroy(profile: str, *extra: str) -> list[str]:
    return dbx("bundle", "destroy", "--auto-approve", *extra, profile=profile)


def lab_schemas(cfg: dict) -> list[str]:
    ws = cfg["workspace"]
    rows = sql(
        f"SELECT schema_name FROM {ws['catalog']}.information_schema.schemata "
        f"WHERE schema_name LIKE '{ws['schema_prefix']}%'",
        cfg,
    )
    return sorted(r["schema_name"] for r in rows if r["schema_name"].startswith(ws["schema_prefix"]))


def drop_schemas(cfg: dict, names: list[str]):
    for name in names:
        sql(f"DROP SCHEMA IF EXISTS {cfg['workspace']['catalog']}.{name} CASCADE", cfg)


def scope_steps() -> list:
    publish = [sys.executable, "genie_one_scope/publish.py", "--remove"]
    return [
        (
            "Genie One skill and workspace instructions (genie_one_scope/publish.py --remove)",
            functools.partial(run, publish, cwd=ROOT),
        )
    ]


def all_steps(cfg: dict, state: dict, include_workbench: bool, drop_data: bool) -> list:
    ws = cfg["workspace"]
    profile = ws["profile"]
    agent_dir = ROOT / "custom_agent"
    agent_vars = [
        f"--var=experiment_id={state['experiment_id']}",
        f"--var=warehouse_id={ws['warehouse_id']}",
        f"--var=trace_schema={state['trace_schema']}",
        f"--var=agent_model={cfg['models']['agent']}",
    ]
    steps = []
    for key, sup in state.get("supervisors", {}).items():
        argv = dbx("supervisor-agents", "delete-supervisor-agent", f"supervisor-agents/{sup['id']}", profile=profile)
        steps.append((f"Supervisor {key}: {sup['id']}", functools.partial(run, argv, cwd=ROOT)))
    steps += scope_steps()
    steps.append(
        (
            f"Fallback agent app {state['fallback_app']} (custom_agent bundle, target dev)",
            functools.partial(run, destroy(profile, "-t", "dev", *agent_vars), cwd=agent_dir),
        )
    )
    if (agent_dir / ".databricks" / "bundle" / "ablation").exists():
        steps.append(
            (
                "Ablation agent app (custom_agent bundle, target ablation)",
                functools.partial(run, destroy(profile, "-t", "ablation", *agent_vars), cwd=agent_dir),
            )
        )
    steps.append(
        (
            f"Lab UI app {state['ui_app']} (app bundle)",
            functools.partial(run, destroy(profile, f"--var=warehouse_id={ws['warehouse_id']}"), cwd=ROOT / "app"),
        )
    )
    for name, space_id in state.get("genie_spaces", {}).items():
        argv = dbx("genie", "trash-space", space_id, profile=profile)
        steps.append((f"Genie Agent {name}: {space_id}", functools.partial(run, argv, cwd=ROOT)))
    dashboard = state.get("dashboard", {})
    if dashboard.get("id"):
        argv = dbx("lakeview", "trash", dashboard["id"], profile=profile)
        steps.append((f"Dashboard {dashboard['name']}: {dashboard['id']}", functools.partial(run, argv, cwd=ROOT)))
    experiments = [state["experiment_id"]] + [s["experiment_id"] for s in state.get("supervisors", {}).values()]
    for exp in experiments:
        argv = dbx("experiments", "delete-experiment", exp, profile=profile)
        steps.append((f"MLflow experiment {exp}", functools.partial(run, argv, cwd=ROOT)))
    steps.append(
        (
            "Data job bundle (root databricks.yml): the generator job and its files",
            functools.partial(run, destroy(profile), cwd=ROOT),
        )
    )
    if include_workbench:
        if not (WORKBENCH / "scripts" / "deploy.sh").exists():
            raise SystemExit(f"{WORKBENCH} is missing, so the Genie Workbench cannot be removed from here")
        steps.append(
            (
                f"Genie Workbench app {state.get('workbench_app', '?')} (its deploy.sh --destroy)",
                functools.partial(run, ["bash", "scripts/deploy.sh", "--destroy", "--auto-approve"], cwd=WORKBENCH),
            )
        )
    if drop_data:
        names = lab_schemas(cfg)
        steps.append(
            (
                f"Schemas {', '.join(names) or '(none)'} in {ws['catalog']}, with all their tables",
                functools.partial(drop_schemas, cfg, names),
            )
        )
    return steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", choices=["scope", "all"], default="scope")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    ap.add_argument("--yes", action="store_true", help="required for --what all")
    ap.add_argument("--include-workbench", action="store_true", help="also remove the Genie Workbench app")
    ap.add_argument("--drop-data", action="store_true", help="also drop the lab schemas and their data")
    args = ap.parse_args()
    if args.what == "scope" and (args.include_workbench or args.drop_data):
        ap.error("--include-workbench and --drop-data only apply to --what all")

    cfg, state = load_config(), load_state()
    steps = scope_steps() if args.what == "scope" else all_steps(cfg, state, args.include_workbench, args.drop_data)

    print("Plan:")
    for text, _ in steps:
        print(f"  - {text}")
    if args.dry_run:
        print("Dry run: nothing was changed.")
        return
    if args.what == "all" and not args.yes:
        raise SystemExit("Nothing was deleted. Read the plan above, then re-run with --yes.")

    failed = []
    for text, action in steps:
        print(f"-> {text}", flush=True)
        try:
            action()
        except (subprocess.CalledProcessError, RuntimeError) as err:
            print(f"   failed: {err}", flush=True)
            failed.append(text)
    if failed:
        raise SystemExit(f"Not finished, {len(failed)} step(s) failed: " + "; ".join(failed))
    print("Done.")


if __name__ == "__main__":
    main()
