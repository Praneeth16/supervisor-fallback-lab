"""Where benchmark rows come from: Delta tables through the SQL Statement Execution API, or fixture files.

Both stores expose the same methods, so the API code does not care which one is active.
"""

import json
import time
from pathlib import Path
from typing import Any

from .config import FIXTURE_DIR, Settings
from .summary import rate

# (column, kind). Kinds: str, int, float, bool, json (JSON array, read through to_json), json_text (JSON in a string).
RUN_COLUMNS = (
    ("run_id", "str"),
    ("run_label", "str"),
    ("arm", "str"),
    ("series", "str"),
    ("grading", "int"),
    ("scoring_version", "str"),
    ("judge", "str"),
    ("benchmark", "str"),
    ("started_at", "str"),
    ("n_questions", "int"),
    ("notes", "str"),
)
RESULT_COLUMNS = (
    ("run_id", "str"),
    ("run_label", "str"),
    ("arm", "str"),
    ("question_id", "str"),
    ("thread_id", "str"),
    ("turn", "int"),
    ("category", "str"),
    ("persona", "str"),
    ("question", "str"),
    ("expected_route", "str"),
    ("expected_behavior", "str"),
    ("answer", "str"),
    ("routes", "json"),
    ("sql", "json"),
    ("tables", "json"),
    ("out_of_scope_tables", "json"),
    ("latency_s", "float"),
    ("approvals", "int"),
    ("error", "str"),
    ("gold_sql", "str"),
    ("gold_result", "json_text"),
    ("correct", "bool"),
    ("route_ok", "bool"),
    ("scope_ok", "bool"),
    ("behavior_ok", "bool"),
    ("clear", "bool"),
    ("passed", "bool"),
    ("correct_rationale", "str"),
    ("behavior_rationale", "str"),
    ("clear_rationale", "str"),
    ("transcript", "json_text"),
    ("trace_id", "str"),
    ("grading", "int"),
    ("unverified_sql", "json"),
    ("no_leak", "bool"),
    ("leak_rationale", "str"),
    ("supervisor_tokens", "int"),
    ("agent_tokens", "int"),
)
GATEWAY_COLUMNS = (
    ("arm", "str"),
    ("service_name", "str"),
    ("service_type", "str"),
    ("tool_name", "str"),
    ("calls", "int"),
    ("total_tokens", "int"),
    ("avg_latency_ms", "float"),
)
GRADING_COLUMNS = (
    ("arm", "str"),
    ("grading", "int"),
    ("scoring_version", "str"),
    ("judge", "str"),
    ("graded_at", "str"),
    ("n", "int"),
    ("passed", "float"),
    ("correct", "float"),
    ("route_ok", "float"),
    ("scope_ok", "float"),
    ("behavior_ok", "float"),
    ("no_leak", "float"),
)
SCOPE_AUDIT_COLUMNS = (
    ("arm", "str"),
    ("client_application", "str"),
    ("statements", "int"),
    ("out_of_scope_statements", "int"),
    ("unanalysed_statements", "int"),
    ("out_of_scope_tables", "json"),
)
DIRECT_TEST_COLUMNS = (
    ("test_id", "str"),
    ("started_at", "str"),
    ("condition", "str"),
    ("request_id", "str"),
    ("kind", "str"),
    ("question", "str"),
    ("sample", "int"),
    ("outcome", "str"),
    ("ok", "bool"),
    ("out_of_scope_tables", "json"),
    ("leak_hits", "json"),
    ("rejected_count", "int"),
)


class StoreError(RuntimeError):
    """The warehouse or a fixture file could not be read."""


def _convert(value: str | None, kind: str) -> Any:
    if value is None:
        return None
    if kind == "str":
        return value
    if kind == "bool":
        return value.strip().lower() == "true"
    if kind == "int":
        return int(float(value))
    if kind == "float":
        return float(value)
    if kind == "json":
        return json.loads(value)
    if kind == "json_text":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    raise ValueError(f"Unknown column kind {kind}")


def _shape(cells: list[list[str | None]], columns: tuple[tuple[str, str], ...]) -> list[dict]:
    return [{name: _convert(value, kind) for (name, kind), value in zip(columns, row, strict=True)} for row in cells]


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _latest_gradings(rows: list[dict]) -> dict[tuple[str, str], int]:
    """Highest grading per (run_label, arm). A missing grading counts as 1, as the SQL store does."""
    latest: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["run_label"], row["arm"])
        latest[key] = max(latest.get(key, 1), row.get("grading") or 1)
    return latest


class FixtureStore:
    """Serves the JSON files in app/backend/fixtures. Used for local work without a workspace."""

    def __init__(self, root: Path = FIXTURE_DIR):
        self._questions = {q["question_id"]: q for q in _load(root / "questions.json")}
        self._runs = _load(root / "runs.json")
        self._results = _load(root / "results.json")
        self._gateway = _load(root / "gateway.json")
        self._tables = _load(root / "tables.json")
        self._ask = _load(root / "ask.json")
        self._direct_test = _load(root / "direct_test_runs.json")
        self._scope_audit = _load(root / "scope_audit.json")

    def runs(self) -> list[dict]:
        latest = _latest_gradings(self._runs)
        return [dict(r) for r in self._runs if (r.get("grading") or 1) == latest[(r["run_label"], r["arm"])]]

    def results(self, run_label: str) -> list[dict]:
        latest = _latest_gradings(self._runs)
        return [
            {**self._questions[stored["question_id"]], **stored}
            for stored in self._results
            if stored["run_label"] == run_label
            and (stored.get("grading") or 1) == latest.get((run_label, stored["arm"]))
        ]

    def gradings(self, run_label: str) -> list[dict]:
        runs = sorted(
            (r for r in self._runs if r["run_label"] == run_label),
            key=lambda r: (r["arm"], r.get("grading") or 1),
        )
        out = []
        for run in runs:
            rows = [r for r in self._results if r["run_id"] == run["run_id"]]
            out.append(
                {
                    "arm": run["arm"],
                    "grading": run.get("grading") or 1,
                    "scoring_version": run.get("scoring_version"),
                    "judge": run.get("judge"),
                    "graded_at": run.get("graded_at"),
                    "n": len(rows),
                    "passed": rate(r.get("passed") for r in rows),
                    "correct": rate(r.get("correct") for r in rows),
                    "route_ok": rate(r.get("route_ok") for r in rows),
                    "scope_ok": rate(r.get("scope_ok") for r in rows),
                    "behavior_ok": rate(r.get("behavior_ok") for r in rows),
                    "no_leak": rate(r.get("no_leak") for r in rows),
                }
            )
        return out

    def gateway(self, run_label: str) -> list[dict]:
        return [dict(g) for g in self._gateway if g["run_label"] == run_label]

    def scope_audit(self, run_label: str) -> list[dict]:
        groups: dict[tuple[str, str], dict] = {}
        for row in self._scope_audit:
            if row["run_label"] != run_label:
                continue
            group = groups.setdefault(
                (row["arm"], row["client_application"]),
                {
                    "arm": row["arm"],
                    "client_application": row["client_application"],
                    "statements": 0,
                    "out_of_scope_statements": 0,
                    "unanalysed_statements": 0,
                    "out_of_scope_tables": set(),
                },
            )
            group["statements"] += 1
            if row.get("out_of_scope_tables"):
                group["out_of_scope_statements"] += 1
            if row.get("analysed") is False:
                group["unanalysed_statements"] += 1
            group["out_of_scope_tables"].update(row.get("out_of_scope_tables") or [])
        return [
            {**group, "out_of_scope_tables": sorted(group["out_of_scope_tables"])}
            for _, group in sorted(groups.items())
        ]

    def allowed_tables(self) -> frozenset[str]:
        return frozenset(t.lower() for t in self._tables)

    def direct_test(self) -> list[dict]:
        return [dict(r) for r in self._direct_test]

    def ask_reply(self, arm: str, question: str) -> dict:
        text = question.lower()
        for match in self._ask["matches"]:
            if any(word in text for word in match["keywords"]):
                return dict(match["replies"][arm])
        return dict(self._ask["default"][arm])


class SqlStore:
    """Reads the lab tables on the app warehouse as the app service principal, with bound parameters."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from databricks.sdk import WorkspaceClient

            self._client = WorkspaceClient()
        return self._client

    def _lab_table(self, name: str) -> str:
        return f"`{self.settings.catalog}`.`{self.settings.schema}`.`{name}`"

    def _execute(self, statement: str, params: dict[str, str] | None = None) -> list[list[str | None]]:
        from databricks.sdk.service.sql import Disposition, Format, StatementParameterListItem, StatementState

        if not self.settings.warehouse_id:
            raise StoreError("DATABRICKS_WAREHOUSE_ID is not set.")
        bound = [StatementParameterListItem(name=k, value=v) for k, v in (params or {}).items()]
        response = self.client.statement_execution.execute_statement(
            statement=statement,
            warehouse_id=self.settings.warehouse_id,
            parameters=bound or None,
            wait_timeout="30s",
            disposition=Disposition.INLINE,
            format=Format.JSON_ARRAY,
        )
        while response.status and response.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            response = self.client.statement_execution.get_statement(response.statement_id)
        state = response.status.state if response.status else None
        if state != StatementState.SUCCEEDED:
            error = response.status.error if response.status else None
            raise StoreError(f"Warehouse query failed: {error.message if error else state}")
        if response.result is None or response.result.data_array is None:
            return []
        return response.result.data_array

    def _execute_if_present(self, statement: str, params: dict[str, str] | None = None) -> list[list[str | None]]:
        """Rows of a table that may not exist yet. Empty when the table is missing."""
        try:
            return self._execute(statement, params)
        except StoreError as error:
            if "TABLE_OR_VIEW_NOT_FOUND" in str(error):
                return []
            raise

    def runs(self) -> list[dict]:
        """The latest grading of each arm of each run. Gradings are kept in the table, so the join picks one."""
        runs = self._lab_table("eval_runs")
        sql = (
            "SELECT r.run_id, r.run_label, r.arm, r.series, COALESCE(r.grading, 1), r.scoring_version, r.judge, "
            "r.benchmark, CAST(r.started_at AS STRING), r.n_questions, r.notes "
            f"FROM {runs} r "
            f"JOIN (SELECT run_label, arm, MAX(COALESCE(grading, 1)) AS grading FROM {runs} "
            "GROUP BY run_label, arm) latest "
            "ON r.run_label = latest.run_label AND r.arm = latest.arm AND COALESCE(r.grading, 1) = latest.grading "
            "ORDER BY r.started_at DESC"
        )
        return _shape(self._execute(sql), RUN_COLUMNS)

    def results(self, run_label: str) -> list[dict]:
        """Result rows of the latest grading of each arm. The grading is taken from eval_runs, not from the results."""
        select = []
        for name, kind in RESULT_COLUMNS:
            expr = "latest.grading" if name == "grading" else f"r.{name}"
            select.append(f"to_json({expr}) AS {name}" if kind == "json" else f"{expr} AS {name}")
        sql = (
            f"SELECT {', '.join(select)} FROM {self._lab_table('eval_results')} r "
            f"JOIN (SELECT run_label, arm, MAX(COALESCE(grading, 1)) AS grading FROM {self._lab_table('eval_runs')} "
            "WHERE run_label = :run_label GROUP BY run_label, arm) latest "
            "ON r.run_label = latest.run_label AND r.arm = latest.arm AND COALESCE(r.grading, 1) = latest.grading "
            "WHERE r.run_label = :run_label ORDER BY r.question_id, r.arm"
        )
        return _shape(self._execute(sql, {"run_label": run_label}), RESULT_COLUMNS)

    def gradings(self, run_label: str) -> list[dict]:
        """Every grading of a run, with the averages of its result rows."""
        sql = (
            "SELECT r.arm, COALESCE(r.grading, 1), MAX(r.scoring_version), MAX(r.judge), "
            "CAST(MAX(r.graded_at) AS STRING), COUNT(res.question_id), "
            "AVG(CAST(res.passed AS INT)), AVG(CAST(res.correct AS INT)), AVG(CAST(res.route_ok AS INT)), "
            "AVG(CAST(res.scope_ok AS INT)), AVG(CAST(res.behavior_ok AS INT)), AVG(CAST(res.no_leak AS INT)) "
            f"FROM {self._lab_table('eval_runs')} r "
            f"LEFT JOIN {self._lab_table('eval_results')} res ON res.run_id = r.run_id "
            "WHERE r.run_label = :run_label "
            "GROUP BY r.arm, COALESCE(r.grading, 1) ORDER BY r.arm, COALESCE(r.grading, 1)"
        )
        return _shape(self._execute(sql, {"run_label": run_label}), GRADING_COLUMNS)

    def gateway(self, run_label: str) -> list[dict]:
        sql = (
            "SELECT arm, service_name, service_type, tool_name, COUNT(*), SUM(total_tokens), "
            "ROUND(AVG(latency_ms), 0) "
            f"FROM {self._lab_table('gateway_usage')} "
            "WHERE run_label = :run_label AND arm IS NOT NULL "
            "GROUP BY arm, service_name, service_type, tool_name "
            "ORDER BY arm, service_name, tool_name"
        )
        return _shape(self._execute(sql, {"run_label": run_label}), GATEWAY_COLUMNS)

    def scope_audit(self, run_label: str) -> list[dict]:
        """Statements the agents ran in a run, grouped by supervisor arm and the service that ran them."""
        sql = (
            "SELECT arm, client_application, COUNT(*), "
            "SUM(CASE WHEN COALESCE(size(out_of_scope_tables), 0) > 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN analysed = false THEN 1 ELSE 0 END), "
            "to_json(array_sort(array_distinct(flatten(collect_list(out_of_scope_tables))))) "
            f"FROM {self._lab_table('scope_audit')} WHERE run_label = :run_label "
            "GROUP BY arm, client_application ORDER BY arm, client_application"
        )
        return _shape(self._execute_if_present(sql, {"run_label": run_label}), SCOPE_AUDIT_COLUMNS)

    def direct_test(self) -> list[dict]:
        """Every request of every direct test (eval/redteam.py). Empty until that test has run."""
        sql = (
            "SELECT test_id, CAST(started_at AS STRING), condition, request_id, kind, question, sample, outcome, ok, "
            "to_json(out_of_scope_tables), to_json(leak_hits), rejected_count "
            f"FROM {self._lab_table('direct_test_runs')}"
        )
        return _shape(self._execute_if_present(sql), DIRECT_TEST_COLUMNS)

    def allowed_tables(self) -> frozenset[str]:
        # The app has no access to the data schemas, so it reads the in-scope table list that
        # scripts/grants.py copies into the lab schema.
        sql = f"SELECT table_catalog, table_schema, table_name FROM {self._lab_table('scope_tables')}"
        return frozenset(".".join(str(part) for part in row).lower() for row in self._execute(sql))


def make_store(settings: Settings) -> FixtureStore | SqlStore:
    return FixtureStore() if settings.fixtures else SqlStore(settings)
