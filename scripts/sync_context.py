"""Build the fallback agent's context folder from Unity Catalog.

For every table in the agent's scope (lab.yaml: scope.fallback and scope.join_only, narrowed by
scope.only_tables when that is set) this writes one markdown file with columns, comments, keys and
sample values, plus the allowlist the SQL guard enforces. The agent can only see and query what
lands in this folder.

Hand-written notes in custom_agent/notes/ are merged in on every run, so they survive a sync:
notes/<schema>.<table>.md goes under that table's description, and the lines of notes/RULES.md are
added to the rules. See custom_agent/notes/README.md.
"""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from labconfig import ROOT, data_rules, load_config, only_tables, schema, sql, tables_in_scope

CONTEXT = ROOT / "custom_agent" / "context"
NOTES = ROOT / "custom_agent" / "notes"
NOTES_HEADING = "## Notes from the data owner"
MAX_SAMPLE_VALUES = 20
SCOPE_RULE = (
    'Tables under "Fallback scope" are yours to answer from. Tables under "Join only" belong to a curated '
    "Genie Agent. Use them to enrich or filter a fallback-scope question, or when one answer needs a join "
    "across them that no single Genie Agent covers (for example refunds joined to what the subscriber watched)."
)


def first_sentence(comment: str | None, limit: int = 180) -> str:
    text = " ".join((comment or "").split())
    end = text.find(". ")
    text = text[: end + 1] if 0 < end < limit else text[:limit]
    return text.rstrip(".")


def table_notes() -> dict[str, str]:
    """Hand-written notes by lower-case schema.table. README.md and RULES.md are not table notes."""
    if not NOTES.is_dir():
        return {}
    return {
        path.stem.lower(): path.read_text().strip()
        for path in sorted(NOTES.glob("*.md"))
        if path.name.lower() not in ("readme.md", "rules.md") and path.read_text().strip()
    }


def extra_rules() -> list[str]:
    """The lines of notes/RULES.md, one rule each. Headings and empty lines are skipped."""
    path = next((p for p in NOTES.glob("*.md") if p.name.lower() == "rules.md"), None) if NOTES.is_dir() else None
    if path is None:
        return []
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line.lstrip("-* ").strip() for line in lines if line and not line.startswith("#")]


def table_doc(cfg: dict, catalog: str, schema_name: str, table: dict, role: str) -> tuple[str, int]:
    name = table["table_name"]
    fq = f"{catalog}.{schema_name}.{name}"
    columns = sql(
        f"SELECT column_name, full_data_type, comment FROM {catalog}.information_schema.columns "
        f"WHERE table_schema = '{schema_name}' AND table_name = '{name}' ORDER BY ordinal_position",
        cfg,
    )
    lines = [f"# {fq}", "", table["comment"] or "", "", f"Scope: {role}."]
    if table["table_type"] == "METRIC_VIEW":
        lines += ["", "This is a metric view. Use MEASURE() on its measures and GROUP BY its dimensions.", ""]
        lines += ["| column | type | description |", "| --- | --- | --- |"]
        lines += [f"| {c['column_name']} | {c['full_data_type']} | {c['comment'] or ''} |" for c in columns]
        return "\n".join(lines) + "\n", 0

    strings = [c["column_name"] for c in columns if c["full_data_type"].upper() == "STRING"]
    profile = sql(
        "SELECT count(*) AS n" + "".join(f", approx_count_distinct(`{c}`) AS `d_{c}`" for c in strings) + f" FROM {fq}",
        cfg,
    )[0]
    rows = int(profile["n"])
    low_card = [c for c in strings if 0 < int(profile[f"d_{c}"]) <= MAX_SAMPLE_VALUES]
    samples = {}
    if low_card:
        values = sql(
            "SELECT "
            + ", ".join(f"to_json(sort_array(collect_set(`{c}`))) AS `{c}`" for c in low_card)
            + f" FROM {fq}",
            cfg,
        )[0]
        samples = {c: ", ".join(json.loads(values[c])) for c in low_card}

    keys = sql(
        f"""SELECT kcu.column_name, tc.constraint_type, pk.table_schema AS ref_schema,
                   pk.table_name AS ref_table, pk.column_name AS ref_column
            FROM {catalog}.information_schema.table_constraints tc
            JOIN {catalog}.information_schema.key_column_usage kcu
              ON tc.constraint_schema = kcu.constraint_schema AND tc.constraint_name = kcu.constraint_name
            LEFT JOIN {catalog}.information_schema.referential_constraints rc
              ON tc.constraint_schema = rc.constraint_schema AND tc.constraint_name = rc.constraint_name
            LEFT JOIN {catalog}.information_schema.key_column_usage pk
              ON rc.unique_constraint_schema = pk.constraint_schema AND rc.unique_constraint_name = pk.constraint_name
            WHERE tc.table_schema = '{schema_name}' AND tc.table_name = '{name}'""",
        cfg,
    )
    lines += [f"Rows: {rows:,}", "", "| column | type | description | values |", "| --- | --- | --- | --- |"]
    lines += [
        f"| {c['column_name']} | {c['full_data_type']} | {c['comment'] or ''} | {samples.get(c['column_name'], '')} |"
        for c in columns
    ]
    pk = [k["column_name"] for k in keys if k["constraint_type"] == "PRIMARY KEY"]
    fks = [k for k in keys if k["constraint_type"] == "FOREIGN KEY"]
    if pk or fks:
        lines += ["", "Keys:"]
        lines += [f"- Primary key: {', '.join(pk)}"] if pk else []
        lines += [
            f"- {k['column_name']} -> {catalog}.{k['ref_schema']}.{k['ref_table']}.{k['ref_column']}" for k in fks
        ]
    return "\n".join(lines) + "\n", rows


def main():
    cfg = load_config()
    catalog = cfg["workspace"]["catalog"]
    scope = cfg["scope"]
    roles = {d: "Fallback scope" for d in scope["fallback"]} | {
        d: "Join only" for d in scope["join_only"] if d not in scope["fallback"]
    }

    # Build into a new folder and swap at the end, so a failed sync leaves the old context in place.
    build = CONTEXT.with_name("context.build")
    if build.exists():
        shutil.rmtree(build)
    (build / "tables").mkdir(parents=True)

    todo = []
    for domain, role in roles.items():
        schema_name = schema(cfg, domain).split(".")[1]
        tables = sql(
            f"SELECT table_name, table_type, comment FROM {catalog}.information_schema.tables "
            f"WHERE {tables_in_scope(cfg, [domain])} ORDER BY table_name",
            cfg,
        )
        todo += [(schema_name, table, role) for table in tables]

    def describe(item):
        schema_name, table, role = item
        doc, rows = table_doc(cfg, catalog, schema_name, table, role)
        return f"{catalog}.{schema_name}.{table['table_name']}", table, role, doc, rows

    notes, used = table_notes(), set()
    allowed, index = [], {"Fallback scope": [], "Join only": []}
    with ThreadPoolExecutor(6) as pool:
        for fq, table, role, doc, rows in pool.map(describe, todo):
            short = fq.split(".", 1)[1].lower()
            if short in notes:
                doc += f"\n{NOTES_HEADING}\n\n{notes[short]}\n"
                used.add(short)
            (build / "tables" / f"{fq}.md").write_text(doc)
            allowed.append(fq)
            size = "metric view" if table["table_type"] == "METRIC_VIEW" else f"{rows:,} rows"
            index[role].append(f"- {fq}: {first_sentence(table['comment'])} ({size})")

    (build / "INDEX.md").write_text(
        "\n\n".join(f"## {role}\n" + "\n".join(entries) for role, entries in index.items() if entries) + "\n"
    )
    owner_rules = extra_rules()
    rules = [SCOPE_RULE, *data_rules(cfg), *owner_rules]
    (build / "RULES.md").write_text("## Rules for this data\n\n" + "\n".join(f"- {r}" for r in rules) + "\n")
    (build / "allowlist.json").write_text(
        json.dumps({"generated_at": datetime.now(UTC).isoformat(), "tables": sorted(allowed)}, indent=2) + "\n"
    )
    if CONTEXT.exists():
        shutil.rmtree(CONTEXT)
    build.rename(CONTEXT)
    print(f"{len(allowed)} tables in scope -> {CONTEXT}")
    print(f"notes: {len(used)} table notes files and {len(owner_rules)} extra rules merged from {NOTES}")
    for short in sorted(set(notes) - used):
        print(f"WARNING: {NOTES.name}/{short}.md matches no table in scope and was not used.")
    listed = only_tables(cfg)
    if listed is not None:
        found = {fq.split(".", 1)[1].lower() for fq in allowed}
        print(f"scope.only_tables is set: {len(found)} of {len(listed)} listed tables found.")
        for short in sorted(listed - found):
            print(f"WARNING: scope.only_tables lists {short}, which does not exist in the catalog.")


if __name__ == "__main__":
    main()
