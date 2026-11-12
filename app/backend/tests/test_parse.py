from labcore.parse import analyse, extract

ALLOWED = frozenset({"c.hoshi_rights.license_agreement", "c.hoshi_content.title"})


def _turn(output: str) -> list[dict]:
    return [{"type": "function_call", "name": "x__genie_ask"}, {"type": "function_call_output", "output": output}]


def test_select_with_cte_and_join():
    sql = (
        "WITH a AS (SELECT * FROM c.hoshi_rights.license_agreement) SELECT * FROM a JOIN c.hoshi_content.title t ON 1=1"
    )
    assert analyse(sql) == (["c.hoshi_content.title", "c.hoshi_rights.license_agreement"], True)


def test_metadata_commands_are_read_by_name():
    assert analyse("SHOW CREATE TABLE c.hoshi_talent.contract") == (["c.hoshi_talent.contract"], True)
    assert analyse("DESCRIBE TABLE `c`.`hoshi_talent`.`contract`") == (["c.hoshi_talent.contract"], True)
    assert analyse("EXPLAIN SELECT * FROM c.hoshi_talent.contract") == (["c.hoshi_talent.contract"], True)
    assert analyse("SHOW TABLES IN c.hoshi_talent") == (["c.hoshi_talent"], True)


def test_table_functions_that_read_data_are_flagged():
    tables, analysed = analyse("SELECT * FROM read_files('/Volumes/x/y')")
    assert analysed and tables == ["table_function:read_files"]
    assert analyse("SELECT id FROM range(10)") == ([], True)


def test_unreadable_sql_is_not_analysed():
    assert analyse("SELEC oops FROM") == ([], False)
    assert analyse("") == ([], False)


def test_out_of_scope_and_fail_closed():
    leak = extract(_turn("```sql\nSHOW COLUMNS IN c.hoshi_talent.contract\n```"), ALLOWED)
    assert leak.out_of_scope == ["c.hoshi_talent.contract"] and not leak.unverified_sql
    unknown = extract(_turn("```sql\nSELEC oops FROM\n```"), ALLOWED)
    assert unknown.unverified_sql == ["SELEC oops FROM"] and not unknown.out_of_scope
    fine = extract(
        _turn("```sql\nSHOW TABLES IN c.hoshi_rights\n```\n```sql\nSELECT 1 FROM c.hoshi_content.title\n```"), ALLOWED
    )
    assert not fine.out_of_scope and not fine.unverified_sql


def test_sql_is_found_in_json_fields_and_progress_lines():
    args = '{"code": "-- check\\nSELECT * FROM c.hoshi_talent.contract", "language": "sql"}'
    sandbox = extract([{"type": "function_call", "name": "sandbox", "arguments": args}], ALLOWED)
    assert sandbox.out_of_scope == ["c.hoshi_talent.contract"]
    progress = extract(
        _turn("Still running.\n• Running SQL: SELECT COUNT(*) FROM `samples`.`nyctaxi`.`trips`\nmore text"), ALLOWED
    )
    assert progress.out_of_scope == ["samples.nyctaxi.trips"]


def test_describe_in_front_of_a_query_is_analysed_as_that_query():
    from labcore.parse import analyse

    query = "WITH w AS (SELECT p.subscriber_id FROM c.s.playback_session AS p) SELECT count(*) FROM w"
    assert analyse(f"DESCRIBE {query}") == (["c.s.playback_session"], True)
    assert analyse(f"EXPLAIN FORMATTED {query}") == (["c.s.playback_session"], True)
    assert analyse("DESCRIBE QUERY SELECT 1 FROM samples.nyctaxi.trips") == (["samples.nyctaxi.trips"], True)
    assert analyse("DESCRIBE TABLE EXTENDED c.s.title") == (["c.s.title"], True)


def test_sql_the_custom_agent_only_suggests_is_not_counted_as_run():
    from labcore.parse import extract

    output = (
        "I cannot read that. You could run this yourself:\n```sql\nSELECT * FROM system.query.history\n```\n"
        "\n\n---\nSource: tables that are not curated for self-service.\n"
        "```sql\nSELECT count(*) FROM c.s.title\n```\nQueries ran as: the calling user"
    )
    items = [{"type": "function_call_output", "output": output}]
    facts = extract(items, frozenset({"c.s.title"}))
    assert facts.sql == ["SELECT count(*) FROM c.s.title"]
    assert facts.shown_sql == ["SELECT * FROM system.query.history"]
    assert facts.out_of_scope == []
    # Without the footer nothing can be split, so everything counts as run.
    plain = extract([{"type": "function_call_output", "output": output.split("\n\n---")[0]}], frozenset())
    assert plain.out_of_scope == ["system.query.history"]
