"""Prepare what the chat in the lab UI needs: its tables, and the app's rights to use them.

  python scripts/setup_chat.py

Creates chat_turns, chat_feedback and chat_preferences in the lab schema (eval/schema.sql), lets the
UI app's service principal read and write them, and lets it attach feedback to the supervisors'
MLflow traces. Run by make app, after the app exists. Safe to run again.
"""

from labconfig import ROOT, api, load_config, load_state, schema, sql

CHAT_TABLES = ("chat_turns", "chat_feedback", "chat_preferences")


def main():
    cfg, state = load_config(), load_state()
    lab = schema(cfg, "lab")
    sp = state.get("ui_app_sp")
    if not sp:
        raise SystemExit("state.json has no ui_app_sp. Run make app first, it deploys the UI and records it.")
    for statement in (ROOT / "eval" / "schema.sql").read_text().format(lab=lab).split(";\n"):
        if any(f".{table} (" in statement for table in CHAT_TABLES):
            sql(statement, cfg)
    for table in CHAT_TABLES:
        sql(f"GRANT SELECT, MODIFY ON TABLE {lab}.{table} TO `{sp}`", cfg)
    print(f"chat tables ready in {lab}, writable by {sp}")

    # The numbers of the Fallback demand page as a view, so a Databricks SQL alert can watch them.
    demand = (cfg.get("ui") or {}).get("fallback_demand") or {}
    min_questions, min_people = int(demand.get("min_questions", 5)), int(demand.get("min_people", 2))
    fallback_schemas = ", ".join(f"'{schema(cfg, d).split('.')[1].lower()}'" for d in cfg["scope"]["fallback"])
    sql(
        f"""CREATE OR REPLACE VIEW {lab}.fallback_demand
            COMMENT 'Tables the fallback was asked about in the chat. candidate: enough questions from enough people to deserve a curated Genie Agent'
            AS WITH asked AS (
              SELECT explode(tables) AS table_name, conversation_id, question, user_email, created_at
              FROM {lab}.chat_turns
              WHERE arrays_overlap(routes, array('genie_one', 'fallback_agent'))),
            counted AS (
              SELECT table_name, count(DISTINCT conversation_id, question) AS questions,
                     count(DISTINCT user_email) AS people, max(created_at) AS last_asked
              FROM asked GROUP BY table_name)
            SELECT *, (questions >= {min_questions} AND people >= {min_people}
                       AND lower(split(table_name, '[.]')[1]) IN ({fallback_schemas})) AS candidate
            FROM counted""",
        cfg,
    )
    print(f"view {lab}.fallback_demand: candidate at {min_questions} questions from {min_people} people")

    # A thumbs up or down is also written to the supervisor's MLflow trace, which needs edit rights.
    for arm, info in (state.get("supervisors") or {}).items():
        experiment = info.get("experiment_id")
        if not experiment:
            continue
        body = {"access_control_list": [{"service_principal_name": sp, "permission_level": "CAN_EDIT"}]}
        try:
            api("patch", f"/api/2.0/permissions/experiments/{experiment}", cfg, body)
            print(f"{arm}: the UI app may add feedback to traces in experiment {experiment}")
        except RuntimeError as error:  # feedback still lands in chat_feedback
            print(f"{arm}: no edit right on experiment {experiment} ({error}). Feedback stays in {lab}.chat_feedback.")


main()
