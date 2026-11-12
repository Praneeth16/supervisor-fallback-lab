"""SQL guard: the code-enforced scope boundary of the fallback agent.

Every statement the model writes passes through `check_sql` before it reaches the warehouse.
A statement runs only if it is a single read-only query whose tables are all on the allowlist.
Anything the guard cannot fully resolve is rejected.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

DIALECT = "databricks"

_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Command,
    exp.Use,
    exp.Set,
    exp.Grant,
    exp.Into,
)

# Functions that read outside Unity Catalog tables, call services, or expose secrets.
_BLOCKED_FUNCTIONS = frozenset(
    {
        "secret",
        "try_secret",
        "reflect",
        "java_method",
        "try_reflect",
        "http_request",
        "remote_query",
        "vector_search",
        "python_exec",
        "identifier",
    }
)
_BLOCKED_FUNCTION_PREFIXES = ("ai_", "read_")


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str | None = None
    tables: tuple[str, ...] = ()
    reason: str | None = None
    row_cap: int | None = None  # set when the guard added or lowered the LIMIT; the query asks for one row more


def _reject(reason: str, tables: set[str] | None = None) -> GuardResult:
    return GuardResult(ok=False, tables=tuple(sorted(tables or ())), reason=reason)


def _function_name(node: exp.Func) -> str:
    name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
    return name.lower()


def _physical_tables(root: exp.Expression) -> list[exp.Table] | None:
    """Table references that are not names of CTEs visible where they are used.

    Returns None when the references cannot all be resolved, so the caller can reject the query.
    """
    physical, seen = [], 0
    for scope in traverse_scope(root):
        for table in scope.tables:
            seen += 1
            source = scope.sources.get(table.alias_or_name)
            is_cte_reference = isinstance(source, Scope) and not table.db and not table.catalog
            if not is_cte_reference:
                physical.append(table)
    if seen != len(list(root.find_all(exp.Table))):
        return None
    return physical


def check_sql(sql: str, allowed: frozenset[str] | None, max_rows: int = 1000) -> GuardResult:
    """Validate `sql` against the table allowlist and return the statement to run.

    `allowed` holds lower-case `catalog.schema.table` names. Passing None turns the allowlist off
    and keeps every other check; that mode exists only for the guard-off ablation in the lab.
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except SqlglotError as e:
        return _reject(f"SQL could not be parsed: {str(e).splitlines()[0]}")

    if len(statements) != 1:
        return _reject(f"Exactly one statement is allowed, found {len(statements)}.")
    root = statements[0]
    while isinstance(root, exp.Subquery) and not root.alias:  # a query wrapped in brackets
        root = root.this

    if not isinstance(root, (exp.Select, exp.SetOperation)):
        return _reject(f"Only SELECT queries are allowed, got {root.key.upper()}.")
    if (write := root.find(*_WRITE_NODES)) is not None:
        return _reject(f"Write or admin operation not allowed: {write.key.upper()}.")

    for func in root.find_all(exp.Func):
        name = _function_name(func)
        if name in _BLOCKED_FUNCTIONS or name.startswith(_BLOCKED_FUNCTION_PREFIXES):
            return _reject(f"Function not allowed: {name}().")
        if isinstance(func, exp.Anonymous) and isinstance(func.parent, exp.Dot):
            return _reject(f"User-defined functions are not allowed: {func.parent.sql(dialect=DIALECT)}.")

    try:
        physical = _physical_tables(root)
    except Exception as e:  # noqa: BLE001 - whatever stops the analysis, the query does not run
        return _reject(f"Table references could not be resolved: {e}")
    if physical is None:
        return _reject("Table references could not be resolved.")

    tables: set[str] = set()
    for table in physical:
        if not isinstance(table.this, exp.Identifier):
            return _reject("Table functions are not allowed; query tables by name.", tables)
        if not (table.catalog and table.db):
            return _reject(
                f"Table `{table.sql(dialect=DIALECT)}` must be fully qualified as catalog.schema.table.",
                tables,
            )
        tables.add(f"{table.catalog}.{table.db}.{table.name}".lower())

    if allowed is not None and (outside := sorted(tables - allowed)):
        return _reject(f"Tables outside the allowed scope: {', '.join(outside)}.", tables)

    limit = root.args.get("limit")
    row_cap = None
    if limit is not None and not limit.expression.is_int:
        return _reject("LIMIT must be a plain number.", tables)
    if limit is None or int(limit.expression.name) > max_rows:
        # Ask for one row more than the cap, so the caller can tell a cut result from a complete one.
        root = root.limit(max_rows + 1)
        row_cap = max_rows

    return GuardResult(ok=True, sql=root.sql(dialect=DIALECT), tables=tuple(sorted(tables)), row_cap=row_cap)
