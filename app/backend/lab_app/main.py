"""FastAPI app for the lab UI: JSON API under /api, the built React app for everything else."""

import asyncio
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .cache import TTLCache
from .config import ARMS, CATEGORIES, STATIC_DIR, Settings, config_payload
from .store import StoreError, make_store
from .summary import direct_test_grid, filter_results, governance, group_runs, question_detail, summary

CACHE_TTL_S = 30.0


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskBody(BaseModel):
    arm: Literal["genie_one", "custom_agent"]
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)


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
    cache = TTLCache(CACHE_TTL_S)

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
