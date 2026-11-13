"""Render and publish the Genie One scope for arm A.

Genie One has no setting that limits it to chosen tables. Its scope is steered with text only:
a skill and the workspace instructions file. This script renders both from lab.yaml and the tables
that exist in Unity Catalog, then publishes them:

1. personal skill      /Users/<me>/.assistant/skills/hoshi-data-scope      (used by Genie One)
2. Unity Catalog skill <catalog>.<prefix>lab.hoshi-data-scope               (attached to supervisor A)
3. workspace file      /Workspace/.genie_workspace_instructions.md          (read by Genie One for every user)

Step 3 touches a file that every Genie One user of the workspace shares. The script backs up what
is there (genie_one_scope/backup/), then adds or replaces only its own marked section and keeps
everything else. `python genie_one_scope/publish.py --remove` deletes the skill and that section;
the file itself is deleted only when the lab created it and nothing else is left in it.
"""

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from labconfig import api, cli, data_rules, load_config, load_state, save_state, schema, sql, tables_in_scope

HERE = Path(__file__).resolve().parent
SKILL_NAME = "hoshi-data-scope"
INSTRUCTIONS_PATH = "/.genie_workspace_instructions.md"
MAX_INSTRUCTION_CHARS = 20_000
MARK_START = (
    "<!-- hoshi-lab-scope:start (written by supervisor-fallback-lab; edits between the markers are overwritten) -->"
)
MARK_END = "<!-- hoshi-lab-scope:end -->"


def objects(cfg: dict, domains: list[str]) -> list[dict]:
    catalog = cfg["workspace"]["catalog"]
    return sql(
        f"SELECT table_schema, table_name, table_type, comment FROM {catalog}.information_schema.tables "
        f"WHERE {tables_in_scope(cfg, domains)} ORDER BY table_schema, table_name",
        cfg,
    )


def bullet(catalog: str, row: dict) -> str:
    comment = (row["comment"] or "").splitlines()[0] if row["comment"] else ""
    return f"- `{catalog}.{row['table_schema']}.{row['table_name']}`: {comment}".rstrip(": ")


def render(cfg: dict, state: dict) -> tuple[str, str]:
    brand, catalog, scope = cfg["brand"], cfg["workspace"]["catalog"], cfg["scope"]
    fallback = objects(cfg, scope["fallback"])
    curated = objects(cfg, [d for d in scope["join_only"] if d not in scope["fallback"]])
    tables = [bullet(catalog, r) for r in fallback if r["table_type"] != "METRIC_VIEW"]
    metric_views = [bullet(catalog, r) for r in fallback if r["table_type"] == "METRIC_VIEW"]
    joins = [bullet(catalog, r) for r in curated]
    off_limits = ", ".join(f"`{schema(cfg, d)}`" for d in scope["off_limits"])
    dashboard = state.get("dashboard")
    dashboard_line = (
        f"- {dashboard['name']} (dashboard id `{dashboard['id']}`)" if dashboard else "- None published yet."
    )

    body = f"""# {brand} data scope

You are answering a data question for {brand}. These rules replace your usual habit of searching
every asset you can see.

## What you may use

Only the objects listed here.

### Tables
{chr(10).join(tables)}

### Metric views
{chr(10).join(metric_views) or "- None."}

### Dashboard
{dashboard_line}

### Tables that belong to curated Genie Agents
Use these to enrich or filter a question about the tables above, or when one answer needs a join
across them that no single Genie Agent covers (for example refunds joined to what the subscriber watched). Do not
use them for a question that one curated Genie Agent can answer on its own.
{chr(10).join(joins)}

## What you must not use

- Any other catalog, schema, table, view, metric view, dashboard, Genie Agent, file or app, even when
  its name looks relevant or it would give a better answer.
- {off_limits}: talent contracts and pay. Off limits in every case.
- Sample data, system tables and information_schema.

## How to answer

1. Write SQL with fully qualified names (catalog.schema.table).
2. If the objects above cannot answer the question, say so, name what is missing, and stop. Do not
   substitute another table.
3. End the answer with the list of tables you used.

## Rules for this data

{chr(10).join(f"- {rule}" for rule in data_rules(cfg))}
"""
    skill = f"""---
name: {SKILL_NAME}
description: Scope rules for {brand} data questions. Use for every question about {brand}, its licensing and rights, royalties, advertising sales, partner deals, subscribers, billing, content or viewing, and whenever a question starts with "{brand} scope".
---

{body}"""
    instructions = f"""{MARK_START}
# {brand} questions

This section applies only when a question mentions "{brand}" or starts with "{brand} scope".
For every other question, ignore it.

{body.split(chr(10), 2)[2]}{MARK_END}
"""
    return skill, instructions


def read_workspace_file(path: str, profile: str) -> str | None:
    """Content of a workspace file, or None when it does not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "file.md"
        try:
            cli("workspace", "export", path, "--file", str(target), "--format", "AUTO", profile=profile)
        except RuntimeError as error:
            if "exist" in str(error).lower() or "not found" in str(error).lower():
                return None
            raise
        return target.read_text()


def write_workspace_file(path: str, content: str, profile: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "file.md"
        source.write_text(content)
        cli("workspace", "import", path, "--file", str(source), "--format", "AUTO", "--overwrite", profile=profile)


def without_lab_section(content: str) -> str:
    if MARK_START not in content:
        return content
    before, rest = content.split(MARK_START, 1)
    after = rest.split(MARK_END, 1)[1] if MARK_END in rest else ""
    return (before.rstrip() + "\n\n" + after.lstrip()).strip()


def merge_instructions(section: str, state: dict, profile: str) -> None:
    """Add or replace the lab's section in the shared Genie instructions file, keeping everything else.

    The file is read by Genie One for every user of the workspace. Whatever is there is backed up
    locally first. The lab only ever touches the text between its two marker lines.
    """
    existing = read_workspace_file(INSTRUCTIONS_PATH, profile)
    created_by_lab = existing is None or state.get("workspace_instructions_created_by_lab", False)
    if existing is not None:
        backup = HERE / "backup" / f"genie_workspace_instructions.{datetime.now(UTC):%Y%m%dT%H%M%SZ}.md"
        backup.parent.mkdir(exist_ok=True)
        backup.write_text(existing)
        previous = HERE / "workspace_instructions.md"
        if MARK_START not in existing and previous.exists() and existing.strip() == previous.read_text().strip():
            existing, created_by_lab = "", True  # the file written by an earlier version of this script
    others = without_lab_section(existing or "")
    content = (others + "\n\n" if others else "") + section
    if len(content) > MAX_INSTRUCTION_CHARS:
        raise SystemExit(
            f"{INSTRUCTIONS_PATH} would be {len(content):,} characters. Genie One ignores everything after "
            f"{MAX_INSTRUCTION_CHARS:,}, so nothing was written. Shorten the scope lists."
        )
    write_workspace_file(INSTRUCTIONS_PATH, content, profile)
    save_state(workspace_instructions=INSTRUCTIONS_PATH, workspace_instructions_created_by_lab=created_by_lab)


def publish(cfg: dict, state: dict):
    profile, catalog = cfg["workspace"]["profile"], cfg["workspace"]["catalog"]
    lab_schema = schema(cfg, "lab").split(".")[1]
    skill, instructions = render(cfg, state)
    (HERE / "skill").mkdir(exist_ok=True)
    (HERE / "skill" / "SKILL.md").write_text(skill)

    user = api("get", "/api/2.0/preview/scim/v2/Me", cfg)["userName"]
    personal = f"/Users/{user}/.assistant/skills/{SKILL_NAME}"
    cli("workspace", "mkdirs", personal, profile=profile)
    cli("workspace", "import", f"{personal}/SKILL.md", "--file", str(HERE / "skill" / "SKILL.md"),
        "--format", "AUTO", "--overwrite", profile=profile)  # fmt: skip

    full_name = f"{catalog}.{lab_schema}.{SKILL_NAME}"
    try:
        api("get", f"/api/2.1/unity-catalog/skills/{full_name}", cfg)
    except RuntimeError as error:
        if "exist" not in str(error).lower() and "not found" not in str(error).lower():
            raise
        api(
            "post",
            f"/api/2.1/unity-catalog/skills?parent=schemas/{catalog}.{lab_schema}&skill_id={SKILL_NAME}",
            cfg,
            {},
        )
    cli("fs", "cp", str(HERE / "skill"), f"dbfs:/Skills/{catalog}/{lab_schema}/{SKILL_NAME}/",
        "--recursive", "--overwrite", profile=profile)  # fmt: skip
    api("post", f"/api/2.1/unity-catalog/skills/{full_name}/finalize", cfg)

    merge_instructions(instructions, state, profile)
    (HERE / "workspace_instructions.md").write_text(instructions)
    save_state(uc_skill=full_name, personal_skill=personal)
    print(f"published: {personal}, {full_name}, {INSTRUCTIONS_PATH}")


def remove(cfg: dict, state: dict):
    profile = cfg["workspace"]["profile"]
    if state.get("personal_skill"):
        cli("workspace", "delete", state["personal_skill"], "--recursive", profile=profile)
    existing = read_workspace_file(INSTRUCTIONS_PATH, profile)
    if existing is not None:
        others = without_lab_section(existing)
        if others:
            write_workspace_file(INSTRUCTIONS_PATH, others + "\n", profile)  # other people's instructions stay
        elif state.get("workspace_instructions_created_by_lab"):
            cli("workspace", "delete", INSTRUCTIONS_PATH, profile=profile)
    if state.get("uc_skill"):
        api("delete", f"/api/2.1/unity-catalog/skills/{state['uc_skill']}", cfg)
    save_state(
        uc_skill=None, personal_skill=None, workspace_instructions=None, workspace_instructions_created_by_lab=None
    )
    print("removed the skill and the lab's section of the workspace instructions")


cfg, state = load_config(), load_state()
remove(cfg, state) if "--remove" in sys.argv else publish(cfg, state)
