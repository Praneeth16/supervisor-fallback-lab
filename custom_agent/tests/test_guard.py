import pytest

from agent_server.guard import check_sql

C = "cat"
ALLOWED = frozenset({f"{C}.hoshi_rights.license_agreement", f"{C}.hoshi_rights.territory", f"{C}.hoshi_content.title"})


def test_simple_select_is_allowed_and_limited():
    r = check_sql(f"SELECT * FROM {C}.hoshi_rights.license_agreement", ALLOWED)
    assert r.ok
    assert r.tables == (f"{C}.hoshi_rights.license_agreement",)
    assert r.sql.endswith("LIMIT 1001") and r.row_cap == 1000


def test_join_cte_and_subquery_inside_scope():
    sql = f"""
    WITH active AS (SELECT * FROM {C}.hoshi_rights.license_agreement WHERE status = 'active')
    SELECT t.title_name, COUNT(*) AS n
    FROM active a JOIN {C}.hoshi_content.title t ON a.title_id = t.title_id
    WHERE a.territory_id IN (SELECT territory_id FROM {C}.hoshi_rights.territory)
    GROUP BY 1
    """
    r = check_sql(sql, ALLOWED)
    assert r.ok, r.reason
    assert len(r.tables) == 3


def test_case_and_backticks_do_not_matter():
    r = check_sql(f"select 1 from `{C.upper()}`.`HOSHI_RIGHTS`.`Territory`", ALLOWED)
    assert r.ok, r.reason


def test_union_is_allowed():
    sql = f"SELECT 1 FROM {C}.hoshi_rights.territory UNION ALL SELECT 2 FROM {C}.hoshi_content.title"
    assert check_sql(sql, ALLOWED).ok


def test_existing_small_limit_is_kept_and_large_limit_is_capped():
    small = check_sql(f"SELECT * FROM {C}.hoshi_rights.territory LIMIT 5", ALLOWED)
    assert small.sql.endswith("LIMIT 5") and small.row_cap is None
    large = check_sql(f"SELECT * FROM {C}.hoshi_rights.territory LIMIT 999999", ALLOWED)
    assert large.sql.endswith("LIMIT 1001") and large.row_cap == 1000


def test_query_in_brackets_is_allowed():
    assert check_sql(f"(SELECT * FROM {C}.hoshi_rights.territory)", ALLOWED).ok


def test_cte_name_does_not_hide_a_table_outside_its_scope():
    # The second `x` is outside the bracketed query, so it is a real table called x, not the CTE.
    r = check_sql("SELECT * FROM (WITH x AS (SELECT 1 AS a) SELECT * FROM x) AS q, x", ALLOWED)
    assert not r.ok and "fully qualified" in r.reason


def test_allowlist_can_be_turned_off_for_the_ablation_but_writes_stay_blocked():
    assert check_sql(f"SELECT * FROM {C}.hoshi_talent.contract", None).ok
    assert not check_sql(f"DROP TABLE {C}.hoshi_talent.contract", None).ok
    assert not check_sql("SELECT * FROM read_files('/Volumes/x/y/z')", None).ok


@pytest.mark.parametrize(
    "sql, fragment",
    [
        (f"SELECT * FROM {C}.hoshi_talent.contract", "outside the allowed scope"),
        (
            f"SELECT * FROM {C}.hoshi_rights.territory WHERE territory_id IN (SELECT a FROM {C}.hoshi_talent.contract)",
            "outside the allowed scope",
        ),
        (
            f"WITH x AS (SELECT * FROM {C}.hoshi_talent.contract) SELECT * FROM x",
            "outside the allowed scope",
        ),
        ("SELECT * FROM system.information_schema.tables", "outside the allowed scope"),
        ("SELECT * FROM hoshi_rights.territory", "fully qualified"),
        ("SELECT * FROM territory", "fully qualified"),
        (f"SELECT 1 FROM {C}.hoshi_rights.territory; DROP TABLE {C}.hoshi_rights.territory", "one statement"),
        (f"DROP TABLE {C}.hoshi_rights.territory", "Only SELECT"),
        (f"INSERT INTO {C}.hoshi_rights.territory SELECT * FROM {C}.hoshi_rights.territory", "Only SELECT"),
        (f"UPDATE {C}.hoshi_rights.territory SET a = 1", "Only SELECT"),
        ("SELECT * FROM read_files('/Volumes/x/y/z')", "not allowed"),
        ("SELECT * FROM range(10)", "Table functions"),
        (f"SELECT * FROM IDENTIFIER('{C}.hoshi_talent.contract')", "not allowed"),
        (f"SELECT ai_query('m', 'hi') FROM {C}.hoshi_rights.territory", "not allowed"),
        (f"SELECT secret('scope', 'key') FROM {C}.hoshi_rights.territory", "not allowed"),
        (f"SELECT {C}.hoshi_rights.my_udf(territory_id) FROM {C}.hoshi_rights.territory", "User-defined functions"),
        (f"SELECT * FROM {C}.hoshi_rights.territory LIMIT 10+5", "LIMIT must be a plain number"),
        ("SELEC oops FROM", "could not be parsed"),
        ("", "one statement"),
    ],
)
def test_rejections(sql, fragment):
    r = check_sql(sql, ALLOWED)
    assert not r.ok
    assert fragment in r.reason
    assert r.sql is None
