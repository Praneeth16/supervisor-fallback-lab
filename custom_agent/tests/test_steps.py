import json

from agent_server.steps import steps_line, tool_steps


def call(name, call_id, **arguments):
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(arguments)}


def output(call_id, text):
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def test_steps_are_listed_in_order_with_sql_outcomes():
    items = [
        call("list_tables", "c1"),
        output("c1", "## Fallback scope"),
        call("read_table", "c2", table="cat.hoshi_sales.campaign"),
        output("c2", "# cat.hoshi_sales.campaign"),
        call("search_tables", "c3", pattern="expir|end_date"),
        output("c3", "No matches."),
        call("run_sql", "c4", sql="SELECT 1 FROM cat.hoshi_talent.contract"),
        output("c4", "REJECTED: cat.hoshi_talent.contract is not on the allowlist"),
        call("run_sql", "c5", sql="SELECT nope FROM cat.hoshi_sales.campaign"),
        output("c5", "SQL ERROR: column nope does not exist"),
        call("run_sql", "c6", sql="SELECT count(*) FROM cat.hoshi_sales.campaign"),
        output("c6", "| n |\n| --- |\n| 35 |"),
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "35"}]},
    ]
    assert steps_line(items) == (
        "Steps: list_tables; read_table hoshi_sales.campaign; "
        'search_tables "expir|end_date"; run_sql rejected; run_sql error; run_sql ok'
    )


def test_no_tool_calls_gives_no_line():
    assert steps_line([{"type": "message", "role": "assistant", "content": "I can't answer this."}]) is None


def test_table_names_lose_the_catalog_and_backticks():
    items = [call("read_table", "c1", table="`cat`.`hoshi_rights`.`territory`"), call("read_table", "c2", table="t")]
    assert tool_steps(items) == ["read_table hoshi_rights.territory", "read_table t"]


def test_patterns_cannot_break_the_line():
    items = [call("search_tables", "c1", pattern='a;b "c"\nd')]
    assert tool_steps(items) == ["search_tables \"a b 'c' d\""]


def test_run_sql_without_a_result_counts_as_error_and_bad_arguments_are_tolerated():
    items = [
        {"type": "function_call", "name": "run_sql", "call_id": "c1", "arguments": "{not json"},
        {"type": "function_call", "name": "read_table", "call_id": "c2", "arguments": "{not json"},
    ]
    assert tool_steps(items) == ["run_sql error", "read_table "]
