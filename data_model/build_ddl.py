"""Create the Hoshi Stream schemas, tables, constraints and scope tags from the MVM subset.

Reads lab.yaml and model_subset.yaml, fetches model.json at the SHA pinned in
model_subset.yaml (into a temp dir, never into this repo), emits the DDL to a temp
file and executes it through `databricks experimental aitools tools query`.
Then runs metric_views.sql unless --skip-metric-views is passed.

Usage: python3 build_ddl.py --root <lab dir> [--skip-metric-views]
       python3 build_ddl.py --root <lab dir> --comments-only   # refresh comments, keeps the data
       python3 build_ddl.py --root <lab dir> --replace         # rebuild existing tables, drops their data

Without --replace the build stops before it changes anything if any lab table already exists.
Schema names use lab.yaml workspace.schema_prefix.

Comments matter: Genie Agents, Genie One and the fallback agent all read them. The model's
descriptions are cleaned of generator notes, and model_subset.yaml can override any table or
column comment with a Hoshi Stream specific one (table_comments, column_comments).
"""

import argparse
import json
import re
import subprocess
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

MODEL_RAW = "https://raw.githubusercontent.com/{repo}/{sha}/{path}"
GH_COMMIT = "https://api.github.com/repos/{repo}/commits/{ref}"


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def pin_sha(subset_path, subset):
    src = subset["source"]
    if src.get("sha"):
        return src["sha"]
    req = urllib.request.Request(
        GH_COMMIT.format(repo=src["repo"], ref="main"),
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        sha = json.load(r)["sha"]
    src["sha"] = sha
    text = subset_path.read_text()
    subset_path.write_text(re.sub(r"(?m)^  sha: .*$", f"  sha: {sha}", text, count=1))
    print(f"pinned model sha {sha}")
    return sha


def fetch_model(src, sha):
    url = MODEL_RAW.format(repo=src["repo"], sha=sha, path=src["path"])
    with urllib.request.urlopen(url, timeout=300) as r:
        return json.load(r)


def index_model(model):
    tables, columns = {}, {}
    for dom in model["model"]["domains"]:
        for p in dom.get("products", []):
            key = f"{dom['name']}.{p['table_name']}"
            tables[key] = p
            for a in p["attributes"]:
                columns[f"{key}.{a['column_name']}"] = a
    return tables, columns


def clean_comment(text):
    """Drop model-generator notes that would mislead an agent reading the comment."""
    text = re.sub(r"\s*\[ENUM-REF-CANDIDATE:[^\]]*\]?", "", str(text or ""))
    text = re.sub(r"\s*Business justification:.*$", "", text, flags=re.DOTALL)
    text = re.sub(r"\s*Role: [A-Z_]+\.?", "", text)
    return text.replace("Media Broadcasting", "Hoshi Stream").strip()


def sql_str(text):
    return "'" + str(text or "").replace("\\", "\\\\").replace("'", "''").replace("\n", " ").strip() + "'"


def build_statements(subset, model_tables, model_cols):
    ext = subset.get("extensions", {})
    table_comments = subset.get("table_comments", {})
    column_comments = subset.get("column_comments", {})
    specs = []
    for t in subset["tables"]:
        key = f"{t['schema']}.{t['table']}"
        product = model_tables[key]
        pk = product["primary_key"]
        cols = []
        fks = []
        for c in t["columns"]:
            ck = f"{key}.{c}"
            if ck in ext:
                e = ext[ck]
                ctype, comment, ref = e["type"], e["comment"], e.get("references")
            else:
                a = model_cols[ck]
                ctype, comment, ref = (
                    a["type"],
                    a.get("description", ""),
                    a.get("foreign_key_to") or None,
                )
            cols.append((c, ctype, column_comments.get(ck) or clean_comment(comment), c == pk))
            if ref:
                fks.append((c, ref))
        specs.append(
            {
                "schema": t["schema"],
                "table": t["table"],
                "key": key,
                "pk": pk,
                "cols": cols,
                "fks": fks,
                "comment": table_comments.get(key) or clean_comment(product.get("description", "")),
                "pk_in_cols": pk in t["columns"],
            }
        )
    return specs


def ordered(specs, subset_keys):
    done, out = set(), []
    pending = list(specs)
    while pending:
        progressed = False
        for s in list(pending):
            deps = {r.rsplit(".", 1)[0] for _, r in s["fks"]} - {s["key"]}
            deps = {d for d in deps if d in subset_keys}
            if deps <= done:
                out.append(s)
                done.add(s["key"])
                pending.remove(s)
                progressed = True
        if not progressed:
            raise SystemExit(f"FK cycle among: {[s['key'] for s in pending]}")
    return out


def table_ddl(cat, prefix, s, subset_keys):
    lines = []
    for name, ctype, comment, is_pk in s["cols"]:
        null = " NOT NULL" if is_pk else ""
        lines.append(f"  `{name}` {ctype}{null} COMMENT {sql_str(comment)}")
    lines.append(f"  CONSTRAINT pk_{s['table']} PRIMARY KEY (`{s['pk']}`) NOT ENFORCED")
    for col, ref in s["fks"]:
        parts = ref.split(".")
        tgt_key, tgt_col = ".".join(parts[:2]), parts[2]
        if tgt_key not in subset_keys:
            continue
        tschema, ttable = tgt_key.split(".")
        lines.append(
            f"  CONSTRAINT fk_{s['table']}_{col} FOREIGN KEY (`{col}`) "
            f"REFERENCES {cat}.{prefix}{tschema}.{ttable} (`{tgt_col}`) NOT ENFORCED"
        )
    return (
        f"CREATE OR REPLACE TABLE {cat}.{prefix}{s['schema']}.{s['table']} (\n"
        + ",\n".join(lines)
        + f"\n) COMMENT {sql_str(s['comment'])}"
    )


def comment_statements(cat, prefix, spec):
    table = f"{cat}.{prefix}{spec['schema']}.{spec['table']}"
    yield f"COMMENT ON TABLE {table} IS {sql_str(spec['comment'])}"
    for name, _, comment, _ in spec["cols"]:
        yield f"ALTER TABLE {table} ALTER COLUMN `{name}` COMMENT {sql_str(comment)}"


def run_sql(profile, warehouse, sql):
    cmd = [
        "databricks",
        "experimental",
        "aitools",
        "tools",
        "query",
        "--profile",
        profile,
        "--warehouse",
        warehouse,
        "--output",
        "json",
        sql,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SystemExit(f"SQL failed:\n{sql[:300]}\n---\n{(r.stderr or r.stdout)[-1500:]}")
    return r.stdout


def split_metric_views(text):
    chunks = re.split(r"(?m)^\$\$;\s*$", text)
    stmts = []
    for ch in chunks:
        body = "\n".join(ln for ln in ch.splitlines() if not ln.lstrip().startswith("--")).strip()
        if body and "CREATE" in body:
            stmts.append(body + "\n$$")
    return stmts


def run_metric_views(profile, warehouse, root, cat, prefix):
    for sql in split_metric_views((root / "data_model" / "metric_views.sql").read_text()):
        run_sql(profile, warehouse, sql.replace("${catalog}", cat).replace("${prefix}", prefix))
        print("ok:", sql.splitlines()[0][:110])


def existing_tables(profile, names):
    w = WorkspaceClient(profile=profile)
    return [n for n in names if w.tables.exists(n).table_exists]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="lab folder (contains lab.yaml)")
    ap.add_argument("--skip-metric-views", action="store_true")
    ap.add_argument("--comments-only", action="store_true", help="only refresh table and column comments")
    ap.add_argument(
        "--metric-views-only",
        action="store_true",
        help="only (re)create metric views; never touches tables or data",
    )
    ap.add_argument(
        "--replace",
        action="store_true",
        help="rebuild tables that already exist; this drops their data",
    )
    args = ap.parse_args()
    root = Path(args.root)
    lab = load_yaml(root / "lab.yaml")["workspace"]
    subset_path = root / "data_model" / "model_subset.yaml"
    subset = load_yaml(subset_path)
    profile, warehouse = lab["profile"], lab["warehouse_id"]
    cat, prefix = lab["catalog"], lab["schema_prefix"]

    if args.metric_views_only:
        run_metric_views(profile, warehouse, root, cat, prefix)
        return

    if not (args.comments_only or args.replace):
        names = [f"{cat}.{prefix}{t['schema']}.{t['table']}" for t in subset["tables"]]
        present = existing_tables(profile, names)
        if present:
            raise SystemExit(
                f"{len(present)} of {len(names)} lab tables already exist (first: {present[0]}). Nothing was changed. "
                "Use --comments-only to refresh comments, or --replace to rebuild the tables and lose their data."
            )

    sha = pin_sha(subset_path, subset)
    model = fetch_model(subset["source"], sha)
    model_tables, model_cols = index_model(model)

    specs = build_statements(subset, model_tables, model_cols)
    subset_keys = {s["key"] for s in specs}
    specs = ordered(specs, subset_keys)

    if args.comments_only:
        # Statements on one table must run one after another (Delta rejects concurrent metadata
        # changes), so tables run in parallel and the comments of each table in sequence.
        def refresh(spec):
            for sql in comment_statements(cat, prefix, spec):
                run_sql(profile, warehouse, sql)

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(refresh, specs))
        print(f"refreshed comments on {len(specs)} tables")
        return

    stmts = []
    for schema, scope in subset["schemas"].items():
        stmts.append(f"CREATE SCHEMA IF NOT EXISTS {cat}.{prefix}{schema}")
        stmts.append(f"ALTER SCHEMA {cat}.{prefix}{schema} SET TAGS ('agent_scope' = '{scope}')")
    for s in specs:
        stmts.append(table_ddl(cat, prefix, s, subset_keys))

    emit = Path(tempfile.gettempdir()) / "hoshi_ddl_emit.sql"
    emit.write_text(";\n\n".join(stmts) + ";\n")
    print(f"emitted {len(stmts)} statements to {emit}")

    for sql in stmts:
        run_sql(profile, warehouse, sql)
        print("ok:", sql.splitlines()[0][:110])

    if not args.skip_metric_views:
        run_metric_views(profile, warehouse, root, cat, prefix)
    print(f"done: {len(specs)} tables in {len(subset['schemas'])} schemas")


if __name__ == "__main__":
    main()
