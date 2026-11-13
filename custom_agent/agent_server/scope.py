"""Loads the agent's context folder: the table allowlist and one description file per table.

The folder is produced by `sync_context.py` from Unity Catalog metadata, so the agent can only
learn about, and only query, tables that were put in scope there.
"""

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONTEXT_DIR = Path(os.environ.get("AGENT_CONTEXT_DIR", Path(__file__).parent.parent / "context"))


@dataclass(frozen=True)
class Scope:
    allowed: frozenset[str]
    index: str
    rules: str


@lru_cache
def load_scope() -> Scope:
    allowlist = json.loads((CONTEXT_DIR / "allowlist.json").read_text())
    rules_file = CONTEXT_DIR / "RULES.md"
    return Scope(
        allowed=frozenset(t.lower() for t in allowlist["tables"]),
        index=(CONTEXT_DIR / "INDEX.md").read_text(),
        rules=rules_file.read_text() if rules_file.exists() else "",
    )


def read_table_doc(table: str, columns: str | None = None) -> str:
    name = table.strip().strip("`").lower()
    if name not in load_scope().allowed:
        return f"`{table}` is not in scope. Use list_tables to see what is available."
    doc = (CONTEXT_DIR / "tables" / f"{name}.md").read_text()
    return filter_columns(doc, columns) if columns else doc


def filter_columns(doc: str, pattern: str) -> str:
    """The table description with only the column rows that match `pattern`.

    For tables with many columns. Everything outside the column table stays: the table comment, the
    row count, the keys and the data owner's notes. A row matches on its name, type, description or
    sample values.
    """
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid columns pattern: {e}"
    lines = doc.splitlines()
    start = next((n for n, line in enumerate(lines) if line.startswith("| column |")), None)
    if start is None:
        return doc
    end = start + 2  # the header row and the separator row
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    rows = lines[start + 2 : end]
    kept = [row for row in rows if regex.search(row)]
    note = f"({len(kept)} of {len(rows)} columns match `{pattern}`. Call read_table without columns to see all.)"
    return "\n".join([*lines[: start + 2], *kept, "", note, *lines[end:]]) + "\n"


def search_context(pattern: str, max_hits: int = 40) -> str:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid pattern: {e}"
    hits = []
    for path in sorted((CONTEXT_DIR / "tables").glob("*.md")):
        for line in path.read_text().splitlines():
            if regex.search(line):
                hits.append(f"{path.stem}: {line.strip()}")
                if len(hits) >= max_hits:
                    return "\n".join(hits) + f"\n(stopped at {max_hits} matches)"
    return "\n".join(hits) or "No matches."
