from types import SimpleNamespace

import pytest
from databricks.sdk.service.sql import StatementState

from lab_app.config import Settings
from lab_app.store import RESULT_COLUMNS, SqlStore, StoreError


class FakeStatements:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute_statement(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def succeeded(rows):
    return SimpleNamespace(
        statement_id="s",
        status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None),
        result=SimpleNamespace(data_array=rows),
    )


def failed(message):
    return SimpleNamespace(
        statement_id="s",
        status=SimpleNamespace(state=StatementState.FAILED, error=SimpleNamespace(message=message)),
        result=None,
    )


def store_with(*responses):
    settings = Settings.from_env({"LAB_FIXTURES": "0", "DATABRICKS_WAREHOUSE_ID": "warehouse-1"})
    fake = FakeStatements(responses)
    store = SqlStore(settings)
    store._client = SimpleNamespace(statement_execution=fake)
    return store, fake


def test_runs_read_only_the_latest_grading_of_each_arm():
    row = ["r1", "v2", "genie_one", "Series", "2", "1.4", "judge", "bench", "2026-11-10 16:40:00", "24", "notes"]
    store, fake = store_with(succeeded([row]))
    (run,) = store.runs()
    assert run["grading"] == 2 and run["scoring_version"] == "1.4" and run["n_questions"] == 24
    sql = fake.calls[0]["statement"]
    assert "MAX(COALESCE(grading, 1))" in sql
    assert "COALESCE(r.grading, 1) = latest.grading" in sql
    assert fake.calls[0]["parameters"] is None


def test_results_join_the_latest_grading_from_eval_runs_and_bind_the_label():
    cells = [None] * len(RESULT_COLUMNS)
    cells[RESULT_COLUMNS.index(("grading", "int"))] = "2"
    store, fake = store_with(succeeded([cells]))
    (row,) = store.results("v2' OR '1'='1")
    assert row["grading"] == 2
    call = fake.calls[0]
    assert "FROM `serverless_lakebase_praneeth_catalog`.`hoshi_lab`.`eval_runs`" in call["statement"]
    assert "COALESCE(r.grading, 1) = latest.grading" in call["statement"]
    assert "OR '1'='1" not in call["statement"]
    assert [(p.name, p.value) for p in call["parameters"]] == [("run_label", "v2' OR '1'='1")]


def test_gradings_join_results_on_run_id_and_convert_rates():
    cells = [
        ["genie_one", "2", "1.4", "judge", "2026-11-11 09:20:00", "24", "0.75", "0.5", "1.0", "0.9", "0.8", "0.75"]
    ]
    store, fake = store_with(succeeded(cells))
    (grading,) = store.gradings("v2")
    assert grading["grading"] == 2 and grading["n"] == 24 and grading["no_leak"] == 0.75
    assert "res.run_id = r.run_id" in fake.calls[0]["statement"]


def test_direct_test_is_empty_when_the_table_is_missing():
    store, _ = store_with(failed("[TABLE_OR_VIEW_NOT_FOUND] The table does not exist."))
    assert store.direct_test() == []


def test_direct_test_reraises_other_warehouse_errors():
    store, _ = store_with(failed("Warehouse is stopped."))
    with pytest.raises(StoreError):
        store.direct_test()


def test_scope_audit_parses_the_distinct_tables():
    cells = [["custom_agent", "sql_mcp_server", "3", "1", "0", '["a.talent.b"]']]
    store, fake = store_with(succeeded(cells))
    (group,) = store.scope_audit("v2")
    assert group == {
        "arm": "custom_agent",
        "client_application": "sql_mcp_server",
        "statements": 3,
        "out_of_scope_statements": 1,
        "unanalysed_statements": 0,
        "out_of_scope_tables": ["a.talent.b"],
    }
    assert "analysed = false" in fake.calls[0]["statement"]
