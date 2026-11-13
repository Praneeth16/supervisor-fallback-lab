import labconfig
import pytest
import sync_context


def config(only=None):
    scope = {
        "genie_agents": {"subscribers_revenue": ["subscriber", "billing"]},
        "fallback": ["rights", "sales"],
        "join_only": ["subscriber", "billing"],
        "off_limits": ["talent"],
    }
    if only is not None:
        scope["only_tables"] = only
    return {"workspace": {"catalog": "Cat", "schema_prefix": "hoshi_"}, "scope": scope}


def test_without_only_tables_the_condition_is_the_schema_list():
    cfg = config()
    assert labconfig.only_tables(cfg) is None
    assert labconfig.tables_in_scope(cfg, ["rights"]) == "table_schema IN ('hoshi_rights')"
    assert (
        labconfig.tables_in_scope(cfg, ["sales", "rights"], always=["billing"])
        == "table_schema IN ('hoshi_billing', 'hoshi_rights', 'hoshi_sales')"
    )


def test_only_tables_accepts_both_spellings_and_ignores_case():
    cfg = config(["hoshi_rights.Territory", "cat.hoshi_sales.campaign", "`hoshi_billing.invoice`"])
    assert labconfig.only_tables(cfg) == {"hoshi_rights.territory", "hoshi_sales.campaign", "hoshi_billing.invoice"}


def test_only_tables_narrows_fallback_schemas_and_leaves_curated_schemas_whole():
    cfg = config(["hoshi_rights.territory", "hoshi_sales.campaign"])
    assert labconfig.tables_in_scope(cfg, ["rights", "sales"]) == (
        "table_schema IN ('hoshi_rights', 'hoshi_sales') AND "
        "lower(concat(table_schema, '.', table_name)) IN ('hoshi_rights.territory', 'hoshi_sales.campaign')"
    )
    both = labconfig.tables_in_scope(cfg, ["rights"], always=["subscriber"])
    assert both.startswith("(table_schema IN ('hoshi_subscriber') OR (table_schema IN ('hoshi_rights') AND ")


@pytest.mark.parametrize("entry", ["campaign", "other.hoshi_sales.campaign", "hoshi_talent.contract", "a.b.c.d"])
def test_only_tables_rejects_entries_that_could_never_be_in_scope(entry):
    with pytest.raises(SystemExit):
        labconfig.only_tables(config([entry]))


def test_notes_are_read_by_schema_and_table_and_rules_line_by_line(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_context, "NOTES", tmp_path)
    (tmp_path / "README.md").write_text("how to use this folder")
    (tmp_path / "Hoshi_Sales.Campaign.md").write_text("\nLive means delivering today.\n")
    (tmp_path / "hoshi_sales.empty.md").write_text("  \n")
    (tmp_path / "RULES.md").write_text("# Our rules\n\n- A week starts on Monday.\nRevenue means net revenue.\n")
    assert sync_context.table_notes() == {"hoshi_sales.campaign": "Live means delivering today."}
    assert sync_context.extra_rules() == ["A week starts on Monday.", "Revenue means net revenue."]


def test_no_notes_folder_means_no_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_context, "NOTES", tmp_path / "missing")
    assert sync_context.table_notes() == {}
    assert sync_context.extra_rules() == []
