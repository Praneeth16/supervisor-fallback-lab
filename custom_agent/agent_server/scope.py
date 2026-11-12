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


def read_table_doc(table: str) -> str:
    name = table.strip().strip("`").lower()
    if name not in load_scope().allowed:
        return f"`{table}` is not in scope. Use list_tables to see what is available."
    return (CONTEXT_DIR / "tables" / f"{name}.md").read_text()


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
