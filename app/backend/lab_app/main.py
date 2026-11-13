"""FastAPI app for the lab UI: JSON API under /api, the built React app for everything else."""

import asyncio
import json
import logging
import os
import queue
import threading
from collections.abc import Iterator
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import chat, chat_store, insights
from .cache import TTLCache
from .config import ARMS, CATEGORIES, STATIC_DIR, Settings, config_payload
from .store import StoreError, make_store
from .summary import (
    direct_test_grid,
    filter_results,
    governance,
    group_runs,
    question_detail,
    question_set,
    summary,
)

CACHE_TTL_S = 30.0
HEARTBEAT_S = 10.0
logger = logging.getLogger(__name__)


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskBody(BaseModel):
    arm: Literal["genie_one", "custom_agent"]
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)


class ChatBody(AskBody):
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    seq: int = Field(default=1, ge=1, le=500)
    mode: Literal["single", "compare"] = "single"


class FeedbackBody(BaseModel):
    turn_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    rating: Literal["up", "down", "none"]
    reasons: list[str] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(default=None, max_length=2000)


class PreferenceBody(BaseModel):
    conversation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    seq: int = Field(ge=1, le=500)
    question: str = Field(max_length=2000)
    choice: Literal["genie_one", "custom_agent", "same", "none"]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _with_heartbeat(events: Iterator[dict]) -> Iterator[str]:
    """Run `events` in a thread and send a comment line while it is quiet, so no proxy closes the stream."""
    box: queue.Queue = queue.Queue()

    def work():
        try:
            for event in events:
                box.put(event)
        except Exception as error:  # the browser must hear about any failure
            logger.exception("chat stream failed")
            box.put({"event": "error", "error": str(error) or type(error).__name__})
        box.put(None)

    threading.Thread(target=work, daemon=True).start()
    while True:
        try:
            event = box.get(timeout=HEARTBEAT_S)
        except queue.Empty:
            yield ": waiting\n\n"
            continue
        if event is None:
            return
        yield _sse(event)


def _user_client(settings: Settings, token: str | None):
    from databricks.sdk import WorkspaceClient

    if token:
        return WorkspaceClient(host=settings.workspace_host, token=token, auth_type="pat")
    return WorkspaceClient()


def _ask_live(settings: Settings, allowed_tables: frozenset[str], body: AskBody, token: str | None) -> dict:
    from labcore import parse, supervisor

    client = _user_client(settings, token)
    history = [{"role": m.role, "content": m.content} for m in body.history]
    history.append({"role": "user", "content": body.question})
    turn = supervisor.ask(client, settings.endpoints[body.arm], history)
    facts = parse.extract(turn.items, allowed_tables)
    return {
        "arm": body.arm,
        "answer": facts.answer,
        "routes": facts.routes,
        "sql": facts.sql,
        "tables": facts.tables,
        "out_of_scope_tables": facts.out_of_scope,
        "latency_s": turn.latency_s,
        "approvals": turn.approvals,
        "error": turn.error,
        "items": turn.items,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = make_store(settings)
    chats = chat_store.make_chat_store(store)
    cache = TTLCache(CACHE_TTL_S)

    def user_of(request: Request) -> dict:
        """The signed-in person. Databricks Apps puts their identity in these headers."""
        email = request.headers.get("x-forwarded-email") or request.headers.get("x-forwarded-user")
        name = request.headers.get("x-forwarded-preferred-username") or email
        if not email:
            email = name = settings.dev_user
        return {"email": email.lower(), "name": name}

    app = FastAPI(title="Hoshi Stream evaluation lab", version="0.1.0")

    @app.exception_handler(StoreError)
    def _store_error(_: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    def runs() -> list[dict]:
        return cache.get_or_load("runs", lambda: group_runs(store.runs()))

    def rows(run_label: str) -> list[dict]:
        return cache.get_or_load(("rows", run_label), lambda: store.results(run_label))

    def gateway(run_label: str) -> list[dict]:
        return cache.get_or_load(("gateway", run_label), lambda: store.gateway(run_label))

    def resolve(run_label: str | None) -> str | None:
        labels = [r["run_label"] for r in runs()]
        if not run_label:
            return labels[0] if labels else None
        if run_label not in labels:
            raise HTTPException(status_code=404, detail=f"No run named {run_label}.")
        return run_label

    @app.get("/api/config")
    def get_config() -> dict:
        return config_payload(settings)

    @app.get("/api/runs")
    def get_runs() -> list[dict]:
        return [
            {
                "run_label": r["run_label"],
                "started_at": r["started_at"],
                "notes": r["notes"],
                "arms": r["arms"],
                "n_questions": r["n_questions"],
                "series": r["series"],
                "grading": r["grading"],
                "scoring_version": r["scoring_version"],
                "judge": r["judge"],
                "benchmark": r["benchmark"],
            }
            for r in runs()
        ]

    @app.get("/api/summary")
    def get_summary(run_label: str | None = None) -> dict:
        label = resolve(run_label)
        if label is None:
            return summary(None, [], [], ARMS, CATEGORIES)
        return cache.get_or_load(
            ("summary", label),
            lambda: summary(label, rows(label), gateway(label), ARMS, CATEGORIES),
        )

    @app.get("/api/results")
    def get_results(
        run_label: str | None = None,
        arm: str | None = None,
        category: str | None = None,
        passed: str | None = None,
    ) -> list[dict]:
        if arm and arm not in ARMS:
            raise HTTPException(status_code=422, detail=f"Unknown arm {arm}.")
        if category and category not in CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Unknown category {category}.")
        if passed not in (None, "", "true", "false"):
            raise HTTPException(status_code=422, detail="passed must be true or false.")
        label = resolve(run_label)
        if label is None:
            return []
        flag = None if passed in (None, "") else passed == "true"
        return filter_results(rows(label), arm=arm or None, category=category or None, passed=flag)

    @app.get("/api/questions")
    def get_questions(run_label: str | None = None) -> list[dict]:
        """The question set of a run with the reference SQL and its result, which is the ground truth."""
        label = resolve(run_label)
        if label is None:
            return []
        return cache.get_or_load(("questions", label), lambda: question_set(rows(label), ARMS))

    @app.get("/api/results/{run_label}/{question_id}")
    def get_result(run_label: str, question_id: str) -> dict:
        detail = question_detail(rows(resolve(run_label)), ARMS, question_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"No question {question_id} in run {run_label}.")
        return detail

    @app.get("/api/governance")
    def get_governance(run_label: str | None = None) -> dict:
        label = resolve(run_label)
        if label is None:
            return governance(None, [], [], ARMS)
        return cache.get_or_load(
            ("governance", label),
            lambda: governance(label, rows(label), gateway(label), ARMS),
        )

    @app.get("/api/gradings")
    def get_gradings(run_label: str | None = None) -> list[dict]:
        label = resolve(run_label)
        if label is None:
            return []
        return cache.get_or_load(("gradings", label), lambda: store.gradings(label))

    @app.get("/api/scope-audit")
    def get_scope_audit(run_label: str | None = None) -> list[dict]:
        label = resolve(run_label)
        if label is None:
            return []
        return cache.get_or_load(("scope_audit", label), lambda: store.scope_audit(label))

    @app.get("/api/direct-test")
    def get_direct_test() -> dict:
        """The latest direct test: out-of-scope requests sent straight to each fallback, by condition and request."""
        return cache.get_or_load("direct_test", lambda: direct_test_grid(store.direct_test()))

    @app.post("/api/ask")
    async def post_ask(body: AskBody, request: Request) -> dict:
        if settings.fixtures:
            await asyncio.sleep(1.5)
            reply = store.ask_reply(body.arm, body.question)
            return {"arm": body.arm, **reply, "error": None}
        token = request.headers.get("x-forwarded-access-token")
        allowed = cache.get_or_load("allowed_tables", store.allowed_tables)
        return await asyncio.to_thread(_ask_live, settings, allowed, body, token)

    @app.get("/api/me")
    def get_me(request: Request) -> dict:
        return user_of(request)

    @app.post("/api/chat/stream")
    def post_chat_stream(body: ChatBody, request: Request) -> StreamingResponse:
        """One question to one supervisor, answered as an event stream: steps, text, then the final facts."""
        user = user_of(request)
        token = request.headers.get("x-forwarded-access-token")
        turn_id = chat_store.new_id()
        conversation_id = body.conversation_id or chat_store.new_id()
        history = [{"role": m.role, "content": m.content} for m in body.history]
        history.append({"role": "user", "content": body.question})

        def events() -> Iterator[dict]:
            yield {"event": "start", "turn_id": turn_id, "conversation_id": conversation_id, "arm": body.arm}
            if settings.fixtures:
                reply = store.ask_reply(body.arm, body.question)
                source = chat.replay(reply.get("items", []), reply, pace_s=settings.fixture_pace_s)
            else:
                allowed = cache.get_or_load("allowed_tables", store.allowed_tables)
                source = chat.run_turn(_user_client(settings, token), settings.endpoints[body.arm], history, allowed)
            final = None
            for event in source:
                if event["event"] == "final":
                    final = {**event, "turn_id": turn_id, "conversation_id": conversation_id}
                    yield final
                else:
                    yield event
            if final is None:
                return
            record = chat_store.turn_record(
                turn_id=turn_id, conversation_id=conversation_id, user_email=user["email"], arm=body.arm,
                mode=body.mode, seq=body.seq, question=body.question, final=final,
            )  # fmt: skip
            try:
                chats.save_turn(record)
                yield {"event": "saved", "turn_id": turn_id}
            except StoreError as error:
                yield {"event": "save_error", "turn_id": turn_id, "error": str(error)}

        return StreamingResponse(
            _with_heartbeat(events()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/chat/conversations")
    def get_conversations(request: Request) -> list[dict]:
        return chats.conversations(user_of(request)["email"])

    @app.get("/api/chat/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, request: Request) -> dict:
        found = chats.conversation(conversation_id, user_of(request)["email"])
        if found is None:
            raise HTTPException(status_code=404, detail="No such conversation of yours.")
        return found

    def log_to_mlflow(turn: dict, body: FeedbackBody, email: str) -> bool:
        """Attach the rating to the supervisor's MLflow trace as a human assessment. Best effort."""
        if settings.fixtures or not turn.get("trace_id") or body.rating == "none":
            return False
        rationale = "; ".join([*body.reasons, *([body.comment] if body.comment else [])]) or None
        assessment = {
            "assessment_name": "user_feedback",
            "trace_id": turn["trace_id"],
            "source": {"source_type": "HUMAN", "source_id": email},
            "feedback": {"value": body.rating == "up"},
        }
        if rationale:
            assessment["rationale"] = rationale
        try:
            store.client.api_client.do(
                "POST", f"/api/3.0/mlflow/traces/{turn['trace_id']}/assessments", body={"assessment": assessment}
            )
            return True
        except Exception as error:  # the rating is still kept in the lab table
            logger.warning("could not log feedback to MLflow trace %s: %s", turn["trace_id"], error)
            return False

    @app.post("/api/feedback")
    def post_feedback(body: FeedbackBody, request: Request) -> dict:
        user = user_of(request)
        turn = chats.turn(body.turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail="That answer is not saved yet. Try again in a moment.")
        logged = log_to_mlflow(turn, body, user["email"])
        chats.save_feedback(
            {
                "feedback_id": chat_store.new_id(),
                "turn_id": turn["turn_id"],
                "conversation_id": turn["conversation_id"],
                "user_email": user["email"],
                "arm": turn["arm"],
                "rating": body.rating,
                "reasons": body.reasons if body.rating == "down" else [],
                "comment": (body.comment or "").strip() or None,
                "trace_id": turn.get("trace_id"),
                "mlflow_logged": logged,
                "created_at": chat_store._now(),
            }
        )
        return {"ok": True, "mlflow_logged": logged}

    @app.post("/api/preference")
    def post_preference(body: PreferenceBody, request: Request) -> dict:
        chats.save_preference(
            {
                "preference_id": chat_store.new_id(),
                "conversation_id": body.conversation_id,
                "seq": body.seq,
                "user_email": user_of(request)["email"],
                "question": body.question,
                "choice": body.choice,
                "created_at": chat_store._now(),
            }
        )
        return {"ok": True}

    @app.get("/api/monitor/activity")
    def get_activity() -> dict:
        return insights.activity(chats.rated_turns(), ARMS)

    @app.get("/api/feedback/summary")
    def get_feedback_summary() -> dict:
        return insights.feedback_summary(chats.rated_turns(), chats.preference_votes(), ARMS)

    @app.get("/api/demand")
    def get_demand() -> dict:
        return insights.fallback_demand(
            chats.rated_turns(), settings.scope, settings.schema_prefix,
            settings.demand_min_questions, settings.demand_min_people,
        )  # fmt: skip

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            return JSONResponse(
                {"detail": "The frontend is not built. Run npm run build in app/frontend."}, status_code=503
            )
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)

    return app


def run() -> None:
    import uvicorn

    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)
