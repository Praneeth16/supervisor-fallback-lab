"""Turns a supervisor transcript into facts: which agents were used, what SQL ran, which tables
were touched and whether any of them were outside the agreed scope.

The scope check fails closed: SQL that cannot be analysed counts against the turn. It only sees SQL
that appears in the transcript, and for Genie One it cannot tell SQL that ran from SQL that was only
shown, so both count. Curated Genie Agents do not show their SQL there, so the
execution-level check in eval/verify_scope.py (query history) is the authority for what really ran.
"""

import json
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# Tool-name fragments, checked in order, mapped to route labels. Supervisor tool ids are chosen
# in supervisors/create.py so that these fragments match.
ROUTE_PATTERNS = (
    ("genie_one", "genie_one"),
    ("ask_fallback_agent", "fallback_agent"),
    ("subscribers_revenue", "genie:subscribers_revenue"),
    ("content_viewing", "genie:content_viewing"),
    ("sandbox", "sandbox"),
)
_CALL_TYPES = ("function_call", "mcp_approval_request", "mcp_call")
_SQL_BLOCK = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_RUNNING_SQL = re.compile(r"Running SQL:\s*(.+)")
_SQL_KEYS = ("query", "sql", "statement")
_SQL_START = re.compile(
    r"\s*(--|/\*|\(|(select|with|show|describe|desc|explain|insert|update|delete|merge|create|drop)\b)", re.I
)
# Start of the footer that custom_agent/agent_server/agent.py appends to every answer.
_AGENT_FOOTER = "\n---\nSource:"
_PART = r"(?:`[^`]+`|[A-Za-z_][\w$]*)"
_THREE_PART_NAME = re.compile(rf"({_PART}\.{_PART}\.{_PART})")
_TWO_OR_THREE_PART_NAME = re.compile(rf"({_PART}(?:\.{_PART}){{1,2}})")
_METADATA_COMMAND = re.compile(r"\s*(show|describe|desc|explain)\b", re.I)
# DESCRIBE or EXPLAIN in front of a whole query, which Genie Agents use to check a query before they run it.
_WRAPPED_QUERY = re.compile(
    r"\s*(?:(?:describe|desc)(?:\s+query)?|explain(?:\s+(?:extended|codegen|cost|formatted))?)\s+"
    r"(?=select\b|with\b|values\b|\()",
    re.I,
)
# Table-valued functions that generate rows and read no stored data.
_HARMLESS_TABLE_FUNCTIONS = frozenset(
    {"range", "explode", "explode_outer", "posexplode", "inline", "stack", "sequence"}
)


@dataclass
class Facts:
    answer: str = ""
    routes: list[str] = field(default_factory=list)  # distinct, in order of first use
    sql: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    unverified_sql: list[str] = field(default_factory=list)  # statements whose tables could not be determined
    shown_sql: list[str] = field(default_factory=list)  # SQL the custom agent wrote in its text and did not run


def route_of(tool_name: str) -> str:
    name = (tool_name or "").lower()
    for fragment, route in ROUTE_PATTERNS:
        if fragment in name:
            return route
    return f"other:{name}"


def _text_of(item: dict) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content or [] if isinstance(p, dict))


def _sql_in(value) -> list[str]:
    """Find SQL inside a tool argument or output: fenced blocks, progress lines, or JSON fields."""
    if isinstance(value, str):
        found = [m.strip() for m in _SQL_BLOCK.findall(value)]
        fenced = _SQL_BLOCK.sub("", value)
        found += [m.strip() for m in _RUNNING_SQL.findall(fenced)]
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return found
        return found + (_sql_in(parsed) if isinstance(parsed, (dict, list)) else [])
    if isinstance(value, dict):
        found = []
        for key, inner in value.items():
            is_sql_field = key in _SQL_KEYS or (key == "code" and str(value.get("language", "")).lower() == "sql")
            if is_sql_field and isinstance(inner, str) and _SQL_START.match(inner):
                found.append(inner.strip())
            else:
                found += _sql_in(inner)
        return found
    if isinstance(value, list):
        return [s for inner in value for s in _sql_in(inner)]
    return []


def _split_agent_output(output) -> tuple[list[str], list[str]]:
    """Return (SQL that ran, SQL that was only shown) for one tool output.

    The custom agent ends every answer with a footer built by its code, which lists the statements
    it ran. SQL above that footer is text the model wrote, for example a query it suggests the user
    run elsewhere, and did not run. Outputs without the footer, such as Genie One's, cannot be split
    this way, so all their SQL counts as run.
    """
    if isinstance(output, str) and _AGENT_FOOTER in output:
        body, footer = output.rsplit(_AGENT_FOOTER, 1)
        return _sql_in(footer), _sql_in(body)
    return _sql_in(output), []


def _normalise(name: str) -> str:
    return name.replace("`", "").lower()


def _table_function_name(node: exp.Expression) -> str:
    name = node.name if isinstance(node, exp.Anonymous) else getattr(node, "sql_name", lambda: node.key)()
    return str(name).lower()


def analyse(sql: str) -> tuple[list[str], bool]:
    """Return (objects referenced, analysed). `analysed` is False when they could not be determined.

    Normal queries are parsed. Metadata commands (SHOW, DESCRIBE, EXPLAIN) and statements the
    parser cannot read are scanned for qualified names instead. Table functions that read data are
    reported as `table_function:<name>`, which is never on an allowlist.
    """
    wrapped = _WRAPPED_QUERY.match(sql)
    if wrapped:
        return analyse(sql[wrapped.end() :])
    if _METADATA_COMMAND.match(sql):
        names = sorted({_normalise(n) for n in _TWO_OR_THREE_PART_NAME.findall(sql)})
        return names, bool(names)
    try:
        statements = [s for s in sqlglot.parse(sql, read="databricks") if s is not None]
    except SqlglotError:
        statements = []
    if not statements or any(isinstance(s, exp.Command) for s in statements):
        names = sorted({_normalise(n) for n in _THREE_PART_NAME.findall(sql)})
        return names, bool(names)
    tables: set[str] = set()
    for statement in statements:
        ctes = {c.alias_or_name.lower() for c in statement.find_all(exp.CTE)}
        for t in statement.find_all(exp.Table):
            if not isinstance(t.this, exp.Identifier):
                function = _table_function_name(t.this)
                if function not in _HARMLESS_TABLE_FUNCTIONS:
                    tables.add(f"table_function:{function}")
                continue
            if not t.db and t.name.lower() in ctes:
                continue
            tables.add(".".join(p for p in (t.catalog, t.db, t.name) if p).lower())
    return sorted(tables), True


def tables_in(sql: str) -> list[str]:
    """Tables referenced by `sql`, lower-case, as written (CTE names excluded)."""
    return analyse(sql)[0]


def extract(items: list[dict], allowed_tables: frozenset[str]) -> Facts:
    """`allowed_tables` holds lower-case catalog.schema.table names the arm may touch."""
    facts = Facts()
    for item in items:
        kind = item.get("type")
        if kind in _CALL_TYPES:
            route = route_of(item.get("name", ""))
            if route not in facts.routes:
                facts.routes.append(route)
            # The built-in sandbox is the one tool whose SQL sits in the call arguments.
            if route == "sandbox":
                facts.sql += _sql_in(item.get("arguments"))
            if kind == "mcp_call":
                facts.sql += _sql_in(item.get("output"))
        elif kind == "function_call_output":
            ran, shown = _split_agent_output(item.get("output"))
            facts.sql += ran
            facts.shown_sql += shown
        elif kind == "message" and item.get("role") == "assistant":
            facts.answer = _text_of(item) or facts.answer

    facts.sql = list(dict.fromkeys(facts.sql))
    tables: set[str] = set()
    for statement in facts.sql:
        found, analysed = analyse(statement)
        tables |= set(found)
        if not analysed:
            facts.unverified_sql.append(statement)
    facts.tables = sorted(tables)
    # A schema name (from SHOW TABLES IN ...) is in scope when it holds an allowed table.
    allowed_schemas = {t.rsplit(".", 1)[0] for t in allowed_tables}
    facts.out_of_scope = [t for t in facts.tables if t not in allowed_tables and t not in allowed_schemas]
    return facts
