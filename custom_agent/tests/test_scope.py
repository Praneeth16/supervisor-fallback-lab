import json

import pytest

from agent_server import scope

TABLE = "cat.hoshi_sales.campaign"
DOC = """# cat.hoshi_sales.campaign

Advertising campaigns.

Scope: Fallback scope.
Rows: 120

| column | type | description | values |
| --- | --- | --- | --- |
| campaign_id | STRING | Key of the campaign |  |
| campaign_status | STRING | Where the campaign stands | Draft, Live, Ended |
| budget_amount | DECIMAL(18,2) | Planned spend in US dollars |  |
| start_date | DATE | First day of delivery |  |

Keys:
- Primary key: campaign_id

## Notes from the data owner

| value | meaning |
| --- | --- |
| Live | delivering today |
"""


@pytest.fixture
def context(tmp_path, monkeypatch):
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / f"{TABLE}.md").write_text(DOC)
    (tmp_path / "INDEX.md").write_text(f"- {TABLE}: Advertising campaigns")
    (tmp_path / "allowlist.json").write_text(json.dumps({"tables": [TABLE]}))
    monkeypatch.setattr(scope, "CONTEXT_DIR", tmp_path)
    scope.load_scope.cache_clear()
    yield
    scope.load_scope.cache_clear()


def test_read_table_without_columns_returns_the_whole_description(context):
    assert scope.read_table_doc(TABLE) == DOC
    assert scope.read_table_doc(TABLE, None) == DOC
    assert scope.read_table_doc(TABLE, "") == DOC


def test_columns_keeps_matching_rows_and_everything_outside_the_column_table(context):
    out = scope.read_table_doc(TABLE, "status|budget")
    assert "| campaign_status |" in out and "| budget_amount |" in out
    assert "| campaign_id |" not in out and "| start_date |" not in out
    assert "(2 of 4 columns match `status|budget`." in out
    # Header, row count, keys and the owner's notes stay, including a table inside the notes.
    for kept in (
        "# cat.hoshi_sales.campaign",
        "Rows: 120",
        "- Primary key: campaign_id",
        "| Live | delivering today |",
    ):
        assert kept in out


def test_columns_matches_descriptions_and_values_without_case(context):
    assert "| campaign_status |" in scope.read_table_doc(TABLE, "ended")
    assert "| budget_amount |" in scope.read_table_doc(TABLE, "SPEND")


def test_bad_pattern_and_table_outside_scope(context):
    assert scope.read_table_doc(TABLE, "(").startswith("Invalid columns pattern")
    assert "not in scope" in scope.read_table_doc("cat.hoshi_talent.contract", "pay")


def test_metric_view_description_has_a_column_table_too(context):
    doc = "# v\n\n| column | type | description |\n| --- | --- | --- |\n| region | STRING | Sales region |\n| revenue | DOUBLE | Measure |\n"
    out = scope.filter_columns(doc, "revenue")
    assert "| revenue |" in out and "| region |" not in out and "(1 of 2 columns" in out
