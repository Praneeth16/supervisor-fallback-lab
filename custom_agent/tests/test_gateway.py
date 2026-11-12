from agent_server import gateway


def _fake(result):
    return lambda w, tool, arguments: {
        "statement_id": "s1",
        "status": {"state": "SUCCEEDED"},
        "manifest": {"schema": {"columns": [{"name": "n"}, {"name": "d"}]}},
        "result": result,
        "total_row_count": 1,
    }


def test_rows_are_read_from_both_result_shapes(monkeypatch):
    monkeypatch.setattr(gateway, "_call", _fake({"data_typed_array": [{"values": [{"str": "600"}, {}]}]}))
    assert gateway.run_statement(None, "SELECT 1")["rows"] == [["600", None]]
    json_shape = {"data_array": [{"values": [{"string_value": "600"}, {"null_value": "NULL_VALUE"}]}]}
    monkeypatch.setattr(gateway, "_call", _fake(json_shape))
    assert gateway.run_statement(None, "SELECT 1")["rows"] == [["600", None]]
