import json

import pytest
from fastapi.testclient import TestClient

from lab_app import chat, insights
from lab_app.chat_store import MemoryChatStore
from lab_app.config import ARMS, DEFAULT_SCOPE, Settings
from lab_app.main import create_app
from lab_app.store import FixtureStore


@pytest.fixture
def client():
    return TestClient(create_app(Settings.from_env({"LAB_FIXTURES": "1", "LAB_FIXTURE_PACE_S": "0"})))


def stream(client, **body) -> list[dict]:
    response = client.post("/api/chat/stream", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def steps_of(arm: str, question: str) -> list[dict]:
    reply = FixtureStore().ask_reply(arm, question)
    events = list(chat.replay(reply["items"], reply))
    return events[-1]["steps"]


def test_genie_one_steps_show_its_progress_and_its_sql():
    steps = steps_of("genie_one", "how many campaigns are live right now")
    kinds = [s["kind"] for s in steps]
    assert kinds[0] == "note"
    progress = [s["title"] for s in steps if s["kind"] == "progress"]
    assert progress[0] == "I'll inspect the campaign table and the dashboard."
    assert len(progress) == 3  # each progress line once, although three polls repeat the earlier ones
    call = next(s for s in steps if s["kind"] == "call")
    assert call["title"] == "Genie One answered"
    assert call["status"] == "done"
    assert "hoshi_sales.campaign" in call["sql"][0]
    assert call["link"].startswith("https://")
    assert "Hoshi Stream scope" in call["detail"]  # the scope line the supervisor added is visible


def test_custom_agent_steps_come_from_the_code_built_footer():
    steps = steps_of("custom_agent", "how many campaigns are live right now")
    inner = [s["title"] for s in steps if s["kind"] == "progress"]
    assert inner == ["list_tables", "read_table hoshi_sales.campaign", "run_sql ok", "run_sql ok"]
    call = steps[-1]
    assert call["kind"] == "call" and call["route"] == "fallback_agent"
    assert call["title"] == "Custom agent answered"
    assert call["facts"]["tokens"] == 9412
    assert call["facts"]["identity"] == "the calling user"
    assert len(call["sql"]) == 1


def test_curated_agent_result_is_attached_to_its_call_and_markers_are_dropped():
    steps = steps_of("genie_one", "paying subs on a promo rate")
    assert [s["kind"] for s in steps] == ["note", "call"]
    assert steps[1]["route"] == "genie:subscribers_revenue"
    assert "1508" in steps[1]["result"]
    assert all("<name>" not in s["title"] for s in steps)


def test_the_final_answer_is_not_repeated_as_a_note():
    reply = FixtureStore().ask_reply("custom_agent", "campaign")
    final = list(chat.replay(reply["items"], reply))[-1]
    assert final["answer"].startswith("**35 campaigns**")
    assert all(not s["title"].startswith("**35 campaigns**") for s in final["steps"])


def test_agent_footer_without_a_footer_is_empty():
    assert chat.agent_footer("plain text")["steps"] == []


def test_stream_emits_start_steps_text_final_and_saved(client):
    events = stream(client, arm="custom_agent", question="how many campaigns are live right now")
    names = [e["event"] for e in events]
    assert names[0] == "start" and names[-1] == "saved"
    assert "step" in names and "delta" in names and "final" in names
    final = next(e for e in events if e["event"] == "final")
    assert final["routes"] == ["fallback_agent"]
    assert final["turn_id"] == events[0]["turn_id"]
    assert final["approvals"] == 1


def test_a_saved_turn_shows_up_in_my_conversations_only(client):
    mine = {"x-forwarded-email": "Sam@Example.com"}
    response = client.post(
        "/api/chat/stream", json={"arm": "genie_one", "question": "campaign count", "mode": "single"}, headers=mine
    )
    start = json.loads(response.text.splitlines()[0][6:])
    listed = client.get("/api/chat/conversations", headers=mine).json()
    assert [c["conversation_id"] for c in listed] == [start["conversation_id"]]
    assert listed[0]["title"] == "campaign count"
    detail = client.get(f"/api/chat/conversations/{start['conversation_id']}", headers=mine).json()
    assert detail["turns"][0]["user_email"] == "sam@example.com"
    assert detail["turns"][0]["steps"]
    other = {"x-forwarded-email": "someone.else@example.com"}
    assert client.get(f"/api/chat/conversations/{start['conversation_id']}", headers=other).status_code == 404


def test_feedback_is_kept_per_person_and_the_newest_rating_counts(client):
    me = {"x-forwarded-email": "sam@example.com"}
    events = stream(client, arm="genie_one", question="campaign count")
    turn_id = events[0]["turn_id"]
    assert client.post("/api/feedback", json={"turn_id": turn_id, "rating": "up"}, headers=me).json()["ok"]
    body = {"turn_id": turn_id, "rating": "down", "reasons": ["Wrong number"], "comment": " off by one "}
    assert client.post("/api/feedback", json=body, headers=me).status_code == 200
    summary = client.get("/api/feedback/summary").json()
    row = next(r for r in summary["recent"] if r["turn_id"] == turn_id)
    assert (row["rating"], row["reasons"], row["comment"], row["rated_by"]) == (
        "down", ["Wrong number"], "off by one", "sam@example.com",
    )  # fmt: skip
    assert sum(r["turn_id"] == turn_id for r in summary["recent"]) == 1
    client.post("/api/feedback", json={"turn_id": turn_id, "rating": "none"}, headers=me)
    assert all(r["turn_id"] != turn_id for r in client.get("/api/feedback/summary").json()["recent"])


def test_feedback_for_an_unknown_turn_is_refused(client):
    assert client.post("/api/feedback", json={"turn_id": "0" * 32, "rating": "up"}).status_code == 404
    assert client.post("/api/feedback", json={"turn_id": "nope", "rating": "up"}).status_code == 422


def test_preference_votes_are_counted_once_per_question_and_person(client):
    before = client.get("/api/feedback/summary").json()["preference"]
    vote = {"conversation_id": "a" * 32, "seq": 1, "question": "q", "choice": "genie_one"}
    client.post("/api/preference", json=vote)
    client.post("/api/preference", json={**vote, "choice": "custom_agent"})
    after = client.get("/api/feedback/summary").json()["preference"]
    assert after["custom_agent"] == before["custom_agent"] + 1
    assert after["genie_one"] == before["genie_one"]


def test_feedback_summary_counts_by_assistant_and_person():
    store = MemoryChatStore()
    summary = insights.feedback_summary(store.rated_turns(), store.preference_votes(), ARMS)
    for arm in ARMS:
        row = summary["arms"][arm]
        assert row["up"] + row["down"] <= row["answers"]
        assert row["rated"] == row["up"] + row["down"]
    assert summary["arms"]["genie_one"]["down_reasons"]
    assert sum(summary["preference"].values()) == summary["totals"]["votes"]
    assert {p["user_email"] for p in summary["people"]} >= {"mika.tanaka@example.com", "arjun.rao@example.com"}


def test_demand_flags_fallback_tables_asked_often_by_several_people():
    store = MemoryChatStore()
    demand = insights.fallback_demand(store.rated_turns(), DEFAULT_SCOPE, "hoshi_", min_questions=3, min_people=2)
    by_table = {t["table"].split(".", 1)[1]: t for t in demand["tables"]}
    campaign = by_table["hoshi_sales.campaign"]
    assert campaign["candidate"] and campaign["owner"] == "fallback"
    assert campaign["questions"] >= 3 and campaign["people"] >= 2
    assert demand["tables"][0]["questions"] >= demand["tables"][-1]["questions"]
    outside = by_table["nyctaxi.trips"]
    assert outside["owner"] == "outside" and not outside["candidate"]
    totals = demand["totals"]
    assert totals["to_fallback"] + totals["to_curated"] + totals["no_agent"] == totals["questions"]
    assert totals["to_curated"] == 2


def test_compare_mode_counts_a_question_once_in_demand():
    rows = [
        {"turn_id": f"t{i}", "conversation_id": "c", "user_email": "a@x", "arm": arm, "mode": "compare",
         "question": "q", "routes": [route], "tables": ["cat.hoshi_sales.campaign"], "created_at": "2026-11-12",
         "rating": None, "reasons": [], "comment": None, "rated_by": None, "rated_at": None}
        for i, (arm, route) in enumerate((("genie_one", "genie_one"), ("custom_agent", "fallback_agent")))
    ]  # fmt: skip
    demand = insights.fallback_demand(rows, DEFAULT_SCOPE, "hoshi_", 1, 1)
    assert demand["tables"][0]["questions"] == 1
    assert demand["tables"][0]["arms"] == ["custom_agent", "genie_one"]


def test_activity_lists_the_latest_answers_with_their_rating(client):
    body = client.get("/api/monitor/activity").json()
    assert body["totals"]["answers"] == sum(a["answers"] for a in body["arms"].values())
    assert body["turns"][0]["created_at"] >= body["turns"][-1]["created_at"]
    outside = next(t for t in body["turns"] if t["out_of_scope_tables"])
    assert outside["rating"] == "down" and outside["arm"] == "genie_one"
    assert body["arms"]["genie_one"]["out_of_scope"] == 1
    assert body["arms"]["custom_agent"]["latency_p50_s"] > 0


def test_question_set_has_one_row_per_question_with_the_reference_sql(client):
    questions = client.get("/api/questions", params={"run_label": "v1"}).json()
    assert len(questions) == 24
    with_gold = [q for q in questions if q["gold_sql"]]
    assert with_gold and set(with_gold[0]["passed"]) == {"genie_one", "custom_agent"}
    assert client.get("/api/questions", params={"run_label": "nope"}).status_code == 404


def test_genie_one_progress_lines_are_tidied_and_come_before_the_finished_call():
    assert (
        chat._tidy_progress("Query result: Query returned 2 rows: <!-- begin:q --> | a | b |")
        == "Query returned 2 rows"
    )
    assert chat._tidy_progress("Thinking: Genie: none — I'll look at the table.") == "I'll look at the table."
    steps = steps_of("genie_one", "how many campaigns are live right now")
    assert [s["kind"] for s in steps] == ["note", "progress", "progress", "progress", "call"]
