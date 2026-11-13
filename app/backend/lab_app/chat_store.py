"""Where chat turns, feedback and preference votes are kept.

Three tables in the lab schema (eval/schema.sql): chat_turns, chat_feedback and chat_preferences.
Feedback and votes are append-only. The newest row of a person for a turn is the one that counts,
so a changed or withdrawn rating leaves its history behind.

`SqlChatStore` writes through the app's SQL warehouse as the app service principal. `MemoryChatStore`
keeps everything in memory and is used with fixture data and in tests.
"""

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import FIXTURE_DIR
from .store import SqlStore, StoreError

RATINGS = ("up", "down", "none")
CHOICES = ("genie_one", "custom_agent", "same", "none")
MAX_ANSWER = 20000
MAX_STEPS_JSON = 60000


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def new_id() -> str:
    return uuid.uuid4().hex


def turn_record(*, turn_id, conversation_id, user_email, arm, mode, seq, question, final: dict) -> dict:
    """The row saved for one answered question, from the final event of the stream."""
    return {
        "turn_id": turn_id,
        "conversation_id": conversation_id,
        "user_email": user_email,
        "arm": arm,
        "mode": mode,
        "seq": seq,
        "question": question,
        "answer": (final.get("answer") or "")[:MAX_ANSWER],
        "routes": final.get("routes") or [],
        "sql": final.get("sql") or [],
        "tables": final.get("tables") or [],
        "out_of_scope_tables": final.get("out_of_scope_tables") or [],
        "steps": final.get("steps") or [],
        "latency_s": final.get("latency_s"),
        "approvals": final.get("approvals") or 0,
        "error": final.get("error"),
        "trace_id": final.get("trace_id"),
        "supervisor_tokens": final.get("supervisor_tokens") or 0,
        "created_at": _now(),
    }


def _conversation_list(turns: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for turn in sorted(turns, key=lambda t: (t["created_at"], t["seq"])):
        group = groups.setdefault(
            turn["conversation_id"],
            {"conversation_id": turn["conversation_id"], "title": turn["question"], "mode": turn["mode"],
             "arms": [], "started_at": turn["created_at"], "last_at": turn["created_at"], "questions": 0},
        )  # fmt: skip
        group["last_at"] = max(group["last_at"], turn["created_at"])
        group["questions"] = max(group["questions"], turn["seq"])
        if turn["arm"] not in group["arms"]:
            group["arms"].append(turn["arm"])
    return sorted(groups.values(), key=lambda g: g["last_at"], reverse=True)


class MemoryChatStore:
    def __init__(self, seed: Path | None = FIXTURE_DIR / "chat.json"):
        self._lock = threading.Lock()
        data = json.loads(seed.read_text()) if seed and seed.is_file() else {}
        self._turns: list[dict] = list(data.get("turns", []))
        self._feedback: list[dict] = list(data.get("feedback", []))
        self._preferences: list[dict] = list(data.get("preferences", []))

    def save_turn(self, record: dict) -> None:
        with self._lock:
            self._turns.append(dict(record))

    def conversations(self, user_email: str) -> list[dict]:
        with self._lock:
            return _conversation_list([t for t in self._turns if t["user_email"] == user_email])[:60]

    def conversation(self, conversation_id: str, user_email: str) -> dict | None:
        with self._lock:
            turns = [
                dict(t)
                for t in self._turns
                if t["conversation_id"] == conversation_id and t["user_email"] == user_email
            ]
            if not turns:
                return None
            ratings = self._latest_feedback()
            votes = self._latest_preferences()
        for turn in turns:
            mine = ratings.get((turn["turn_id"], user_email))
            turn["feedback"] = (
                {"rating": mine["rating"], "reasons": mine["reasons"], "comment": mine["comment"]} if mine else None
            )
        turns.sort(key=lambda t: (t["seq"], t["arm"]))
        preferences = {
            str(seq): vote["choice"]
            for (cid, seq, who), vote in votes.items()
            if cid == conversation_id and who == user_email
        }
        return {
            "conversation_id": conversation_id,
            "mode": turns[0]["mode"],
            "turns": turns,
            "preferences": preferences,
        }

    def turn(self, turn_id: str) -> dict | None:
        with self._lock:
            return next((dict(t) for t in self._turns if t["turn_id"] == turn_id), None)

    def save_feedback(self, record: dict) -> None:
        with self._lock:
            self._feedback.append(dict(record))

    def save_preference(self, record: dict) -> None:
        with self._lock:
            self._preferences.append(dict(record))

    def _latest_feedback(self) -> dict[tuple[str, str], dict]:
        latest: dict[tuple[str, str], dict] = {}
        for row in sorted(self._feedback, key=lambda r: r["created_at"]):
            latest[(row["turn_id"], row["user_email"])] = row
        return {key: row for key, row in latest.items() if row["rating"] != "none"}

    def _latest_preferences(self) -> dict[tuple[str, int, str], dict]:
        latest: dict[tuple[str, int, str], dict] = {}
        for row in sorted(self._preferences, key=lambda r: r["created_at"]):
            latest[(row["conversation_id"], row["seq"], row["user_email"])] = row
        return {key: row for key, row in latest.items() if row["choice"] != "none"}

    def rated_turns(self) -> list[dict]:
        """Every saved turn with the ratings people gave it. One row for each turn and rating, or one
        row with no rating."""
        with self._lock:
            ratings = self._latest_feedback()
            turns = [dict(t) for t in self._turns]
        by_turn: dict[str, list[dict]] = {}
        for (turn_id, _), row in ratings.items():
            by_turn.setdefault(turn_id, []).append(row)
        out = []
        for turn in turns:
            base = {k: turn[k] for k in ("turn_id", "conversation_id", "user_email", "arm", "mode", "question",
                                         "routes", "tables", "out_of_scope_tables", "latency_s", "error",
                                         "created_at", "trace_id")}  # fmt: skip
            base["answer"] = (turn["answer"] or "")[:600]
            rows = by_turn.get(turn["turn_id"]) or [None]
            for row in rows:
                out.append(
                    {**base, "rating": row["rating"] if row else None, "reasons": row["reasons"] if row else [],
                     "comment": row["comment"] if row else None, "rated_by": row["user_email"] if row else None,
                     "rated_at": row["created_at"] if row else None}
                )  # fmt: skip
        return out

    def preference_votes(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self._latest_preferences().values()]


class SqlChatStore:
    def __init__(self, store: SqlStore):
        self._store = store

    def _table(self, name: str) -> str:
        return self._store._lab_table(name)

    def _run(self, statement: str, params: dict | None = None) -> list[list[str | None]]:
        try:
            return self._store._execute(statement, params)
        except StoreError as error:
            if "TABLE_OR_VIEW_NOT_FOUND" in str(error):
                raise StoreError(
                    "The chat tables do not exist yet. Run make app, which creates them (scripts/setup_chat.py)."
                ) from error
            raise

    def save_turn(self, record: dict) -> None:
        steps = json.dumps(record["steps"])
        if len(steps) > MAX_STEPS_JSON:
            steps = json.dumps([{**s, "result": None, "detail": None} for s in record["steps"]])[:MAX_STEPS_JSON]
        self._run(
            f"""INSERT INTO {self._table("chat_turns")}
                (turn_id, conversation_id, user_email, arm, mode, seq, question, answer, routes, sql, tables,
                 out_of_scope_tables, steps, latency_s, approvals, error, trace_id, supervisor_tokens, created_at)
                SELECT :turn_id, :conversation_id, :user_email, :arm, :mode, CAST(:seq AS INT), :question, :answer,
                       from_json(:routes, 'ARRAY<STRING>'), from_json(:sql, 'ARRAY<STRING>'),
                       from_json(:tables, 'ARRAY<STRING>'), from_json(:out_of_scope_tables, 'ARRAY<STRING>'),
                       :steps, CAST(:latency_s AS DOUBLE), CAST(:approvals AS INT), :error, :trace_id,
                       CAST(:supervisor_tokens AS INT), current_timestamp()""",
            {
                "turn_id": record["turn_id"],
                "conversation_id": record["conversation_id"],
                "user_email": record["user_email"],
                "arm": record["arm"],
                "mode": record["mode"],
                "seq": str(record["seq"]),
                "question": record["question"],
                "answer": record["answer"],
                "routes": json.dumps(record["routes"]),
                "sql": json.dumps(record["sql"]),
                "tables": json.dumps(record["tables"]),
                "out_of_scope_tables": json.dumps(record["out_of_scope_tables"]),
                "steps": steps,
                "latency_s": None if record["latency_s"] is None else str(record["latency_s"]),
                "approvals": str(record["approvals"]),
                "error": record["error"],
                "trace_id": record["trace_id"],
                "supervisor_tokens": str(record["supervisor_tokens"]),
            },
        )

    def conversations(self, user_email: str) -> list[dict]:
        rows = self._run(
            f"""SELECT conversation_id, min_by(question, struct(seq, created_at)), max(mode),
                       to_json(array_sort(collect_set(arm))), CAST(min(created_at) AS STRING),
                       CAST(max(created_at) AS STRING), max(seq)
                FROM {self._table("chat_turns")} WHERE user_email = :user_email
                GROUP BY conversation_id ORDER BY max(created_at) DESC LIMIT 60""",
            {"user_email": user_email},
        )
        return [
            {"conversation_id": r[0], "title": r[1], "mode": r[2], "arms": json.loads(r[3] or "[]"),
             "started_at": r[4], "last_at": r[5], "questions": int(r[6] or 0)}
            for r in rows
        ]  # fmt: skip

    _TURN_COLUMNS = (
        "t.turn_id, t.conversation_id, t.user_email, t.arm, t.mode, t.seq, t.question, t.answer, to_json(t.routes), "
        "to_json(t.sql), to_json(t.tables), to_json(t.out_of_scope_tables), t.steps, t.latency_s, t.approvals, "
        "t.error, t.trace_id, t.supervisor_tokens, CAST(t.created_at AS STRING)"
    )

    @staticmethod
    def _turn(r: list) -> dict:
        return {
            "turn_id": r[0], "conversation_id": r[1], "user_email": r[2], "arm": r[3], "mode": r[4],
            "seq": int(r[5] or 0), "question": r[6], "answer": r[7] or "", "routes": json.loads(r[8] or "[]"),
            "sql": json.loads(r[9] or "[]"), "tables": json.loads(r[10] or "[]"),
            "out_of_scope_tables": json.loads(r[11] or "[]"), "steps": json.loads(r[12] or "[]"),
            "latency_s": None if r[13] is None else float(r[13]), "approvals": int(r[14] or 0), "error": r[15],
            "trace_id": r[16], "supervisor_tokens": int(r[17] or 0), "created_at": r[18],
        }  # fmt: skip

    def _latest_feedback_sql(self) -> str:
        return (
            f"(SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY turn_id, user_email ORDER BY created_at DESC) "
            f"AS rn FROM {self._table('chat_feedback')}) WHERE rn = 1 AND rating <> 'none')"
        )

    def conversation(self, conversation_id: str, user_email: str) -> dict | None:
        rows = self._run(
            f"""SELECT {self._TURN_COLUMNS}, f.rating, to_json(f.reasons), f.comment
                FROM {self._table("chat_turns")} t
                LEFT JOIN {self._latest_feedback_sql()} f ON f.turn_id = t.turn_id AND f.user_email = :user_email
                WHERE t.conversation_id = :conversation_id AND t.user_email = :user_email
                ORDER BY t.seq, t.arm""",
            {"conversation_id": conversation_id, "user_email": user_email},
        )
        if not rows:
            return None
        turns = []
        for r in rows:
            turn = self._turn(r)
            turn["feedback"] = (
                {"rating": r[19], "reasons": json.loads(r[20] or "[]"), "comment": r[21]} if r[19] else None
            )
            turns.append(turn)
        votes = self._run(
            f"""SELECT seq, choice FROM (
                  SELECT seq, choice, row_number() OVER (PARTITION BY seq ORDER BY created_at DESC) AS rn
                  FROM {self._table("chat_preferences")}
                  WHERE conversation_id = :conversation_id AND user_email = :user_email) WHERE rn = 1""",
            {"conversation_id": conversation_id, "user_email": user_email},
        )
        preferences = {str(int(v[0])): v[1] for v in votes if v[1] != "none"}
        return {
            "conversation_id": conversation_id,
            "mode": turns[0]["mode"],
            "turns": turns,
            "preferences": preferences,
        }

    def turn(self, turn_id: str) -> dict | None:
        rows = self._run(
            f"SELECT {self._TURN_COLUMNS} FROM {self._table('chat_turns')} t WHERE t.turn_id = :turn_id LIMIT 1",
            {"turn_id": turn_id},
        )
        return self._turn(rows[0]) if rows else None

    def save_feedback(self, record: dict) -> None:
        self._run(
            f"""INSERT INTO {self._table("chat_feedback")}
                (feedback_id, turn_id, conversation_id, user_email, arm, rating, reasons, comment, trace_id,
                 mlflow_logged, created_at)
                SELECT :feedback_id, :turn_id, :conversation_id, :user_email, :arm, :rating,
                       from_json(:reasons, 'ARRAY<STRING>'), :comment, :trace_id, CAST(:mlflow_logged AS BOOLEAN),
                       current_timestamp()""",
            {
                "feedback_id": record["feedback_id"],
                "turn_id": record["turn_id"],
                "conversation_id": record["conversation_id"],
                "user_email": record["user_email"],
                "arm": record["arm"],
                "rating": record["rating"],
                "reasons": json.dumps(record["reasons"]),
                "comment": record["comment"],
                "trace_id": record["trace_id"],
                "mlflow_logged": "true" if record["mlflow_logged"] else "false",
            },
        )

    def save_preference(self, record: dict) -> None:
        self._run(
            f"""INSERT INTO {self._table("chat_preferences")}
                (preference_id, conversation_id, seq, user_email, question, choice, created_at)
                SELECT :preference_id, :conversation_id, CAST(:seq AS INT), :user_email, :question, :choice,
                       current_timestamp()""",
            {
                "preference_id": record["preference_id"],
                "conversation_id": record["conversation_id"],
                "seq": str(record["seq"]),
                "user_email": record["user_email"],
                "question": record["question"],
                "choice": record["choice"],
            },
        )

    def rated_turns(self) -> list[dict]:
        rows = self._run(
            f"""SELECT t.turn_id, t.conversation_id, t.user_email, t.arm, t.mode, t.question, left(t.answer, 600),
                       to_json(t.routes), to_json(t.tables), to_json(t.out_of_scope_tables), t.latency_s, t.error,
                       CAST(t.created_at AS STRING), f.rating, to_json(f.reasons), f.comment, f.user_email,
                       CAST(f.created_at AS STRING), t.trace_id
                FROM {self._table("chat_turns")} t
                LEFT JOIN {self._latest_feedback_sql()} f ON f.turn_id = t.turn_id
                ORDER BY t.created_at DESC LIMIT 5000"""
        )
        return [
            {"turn_id": r[0], "conversation_id": r[1], "user_email": r[2], "arm": r[3], "mode": r[4],
             "question": r[5], "answer": r[6] or "", "routes": json.loads(r[7] or "[]"),
             "tables": json.loads(r[8] or "[]"), "out_of_scope_tables": json.loads(r[9] or "[]"),
             "latency_s": None if r[10] is None else float(r[10]), "error": r[11], "created_at": r[12],
             "rating": r[13], "reasons": json.loads(r[14] or "[]"), "comment": r[15], "rated_by": r[16],
             "rated_at": r[17], "trace_id": r[18]}
            for r in rows
        ]  # fmt: skip

    def preference_votes(self) -> list[dict]:
        rows = self._run(
            f"""SELECT conversation_id, seq, user_email, question, choice, CAST(created_at AS STRING) FROM (
                  SELECT *, row_number() OVER (PARTITION BY conversation_id, seq, user_email ORDER BY created_at DESC)
                         AS rn FROM {self._table("chat_preferences")}) WHERE rn = 1 AND choice <> 'none'"""
        )
        return [
            {"conversation_id": r[0], "seq": int(r[1] or 0), "user_email": r[2], "question": r[3], "choice": r[4],
             "created_at": r[5]}
            for r in rows
        ]  # fmt: skip


def make_chat_store(store) -> MemoryChatStore | SqlChatStore:
    return SqlChatStore(store) if isinstance(store, SqlStore) else MemoryChatStore()
