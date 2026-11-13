"""Run a benchmark against both supervisors, grade the answers and store the results.

  python eval/run_eval.py --label v3-holdout-r1 --series v3-holdout --benchmark eval/benchmark_holdout.yaml
  python eval/run_eval.py --label v1 --regrade                    # grade saved answers again
  python eval/run_eval.py --label v4 --collect-only               # ask now, grade later with --regrade
  python eval/run_eval.py --label smoke --ids lt01,lt02 --no-store  # quick partial run, nothing kept

Answers and grades are kept apart:

  eval/results/<label>/<arm>.answers.json     what the supervisor said. Written once, never changed.
  eval/results/<label>/<arm>.grading-<n>.json one grading of those answers: judge verdicts and scores,
                                              with the scoring version, judge model and benchmark hash.

A regrade adds a new grading and keeps the old ones, so a change to the judges, the grading notes
or the scoring rules is always visible next to the earlier result. The Delta tables the UI reads
are append-only in the same way: rows carry a grading number and the UI shows the latest.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import mlflow
import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState
from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "app" / "backend"), str(ROOT / "eval")]

import judges as judge_lib
from labconfig import LAB_SQL_TAG, load_config, load_state, placeholders, schema, sql, tables_in_scope
from labcore.parse import extract
from labcore.supervisor import ask
from scoring import LEAK_CHECKED, SCORING_VERSION, false_fallback, score

RESULTS = ROOT / "eval" / "results"
GOLD_ROW_CAP = 50
JUDGE_TRIES = 4
MLFLOW_TRIES = 3
TRANSCRIPT_CAP = 60_000
AGENT_TOKENS = re.compile(r"Agent tokens: ([\d,]+)")
OUTCOME_FIELDS = (
    "history", "answer", "latency_s", "approvals", "declined", "error", "items", "trace_ids", "supervisor_tokens",
)  # fmt: skip
RUN_COLUMNS = [
    ("run_id", "STRING"), ("run_label", "STRING"), ("series", "STRING"), ("arm", "STRING"), ("grading", "INT"),
    ("scoring_version", "STRING"), ("judge", "STRING"), ("benchmark", "STRING"), ("benchmark_sha", "STRING"),
    ("supervisor_endpoint", "STRING"), ("started_at", "TIMESTAMP"), ("finished_at", "TIMESTAMP"),
    ("graded_at", "TIMESTAMP"), ("n_questions", "INT"), ("mlflow_run_id", "STRING"), ("notes", "STRING"),
]  # fmt: skip
RESULT_COLUMNS = [
    ("run_id", "STRING"), ("run_label", "STRING"), ("arm", "STRING"), ("grading", "INT"), ("question_id", "STRING"),
    ("thread_id", "STRING"), ("turn", "INT"), ("category", "STRING"), ("persona", "STRING"),
    ("question", "STRING"), ("expected_route", "STRING"), ("expected_behavior", "STRING"), ("answer", "STRING"),
    ("routes", "ARRAY<STRING>"), ("sql", "ARRAY<STRING>"), ("tables", "ARRAY<STRING>"),
    ("out_of_scope_tables", "ARRAY<STRING>"), ("unverified_sql", "ARRAY<STRING>"), ("latency_s", "DOUBLE"),
    ("approvals", "INT"), ("error", "STRING"), ("gold_sql", "STRING"), ("gold_result", "STRING"),
    ("correct", "BOOLEAN"), ("route_ok", "BOOLEAN"), ("scope_ok", "BOOLEAN"), ("behavior_ok", "BOOLEAN"),
    ("no_leak", "BOOLEAN"), ("clear", "BOOLEAN"), ("passed", "BOOLEAN"), ("correct_rationale", "STRING"),
    ("behavior_rationale", "STRING"), ("leak_rationale", "STRING"), ("clear_rationale", "STRING"),
    ("transcript", "STRING"), ("trace_id", "STRING"), ("supervisor_tokens", "BIGINT"), ("agent_tokens", "BIGINT"),
]  # fmt: skip


@dataclass
class Row:
    """One benchmark turn for one arm: the question, what happened, and how it was graded."""

    question_id: str
    thread_id: str | None
    turn: int
    category: str
    persona: str
    question: str
    expected_routes: list[str]
    expected_behavior: str
    gold_sql: str | None
    notes: str | None
    must_not_contain: list[str] = field(default_factory=list)
    # what the supervisor did (raw, saved once)
    history: list[dict] = field(default_factory=list)
    answer: str = ""
    latency_s: float = 0.0
    approvals: int = 0
    declined: list[str] = field(default_factory=list)
    error: str | None = None
    items: list[dict] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)
    supervisor_tokens: int = 0
    # derived from the items at grading time
    routes: list[str] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    unverified_sql: list[str] = field(default_factory=list)
    agent_tokens: int = 0
    gold_result: list[dict] | None = None
    gold_truncated: bool = False
    judged: dict = field(default_factory=dict)  # judge name -> {"value", "rationale"}
    earlier_judged: dict = field(default_factory=dict)  # verdicts of the previous grading that may be reused
    leak_hits: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)


def load_cases(cfg: dict, benchmark: Path, only: set[str] | None) -> list[list[Row]]:
    """Return cases; a case is the ordered list of turns of one conversation."""
    spec = yaml.safe_load(benchmark.read_text())
    names = placeholders(cfg)
    drafts = [q["id"] for q in spec.get("questions", []) if q.get("reviewed") is False]
    if drafts:
        raise SystemExit(
            f"{benchmark} has {len(drafts)} questions a person has not reviewed yet ({', '.join(drafts[:6])}...). "
            "Their reference SQL was drafted by a model. Check each one and set reviewed: true first."
        )

    def row(base: dict, turn_spec: dict, qid: str, thread_id: str | None, n: int) -> Row:
        merged = base | turn_spec
        gold = merged.get("gold")
        return Row(
            question_id=qid, thread_id=thread_id, turn=n, category=merged["category"], persona=merged.get("persona", ""),
            question=merged["ask"].strip(), expected_routes=merged.get("routes", []),
            expected_behavior=merged.get("behavior", "answer"),
            gold_sql=gold.format(**names).strip() if gold else None, notes=merged.get("notes"),
            must_not_contain=merged.get("must_not_contain", []),
        )  # fmt: skip

    cases = [[row({}, q, q["id"], None, 1)] for q in spec.get("questions", [])]
    for thread in spec.get("threads", []):
        base = {k: v for k, v in thread.items() if k not in ("id", "turns")}
        cases.append([row(base, t, f"{thread['id']}.{n}", thread["id"], n) for n, t in enumerate(thread["turns"], 1)])
    if only:
        cases = [c for c in cases if any(r.question_id in only or r.thread_id in only for r in c)]
    return cases


def allowed_tables(cfg: dict, fallback_only: bool = False) -> frozenset[str]:
    """Tables the lab's agents may use. With fallback_only, the tables a fallback may use.

    scope.only_tables narrows the fallback's tables and leaves the curated Genie Agents' schemas whole.
    """
    catalog, scope = cfg["workspace"]["catalog"], cfg["scope"]
    curated = () if fallback_only else [d for ds in scope["genie_agents"].values() for d in ds]
    where = tables_in_scope(cfg, [*scope["fallback"], *scope["join_only"]], always=curated)
    rows = sql(f"SELECT table_schema, table_name FROM {catalog}.information_schema.tables WHERE {where}", cfg)
    return frozenset(f"{catalog}.{r['table_schema']}.{r['table_name']}".lower() for r in rows)


def off_limits_canaries(cfg: dict) -> list[str]:
    """Column names that exist only in the off-limits schemas. Seeing one in a refusal is a leak."""
    catalog, scope = cfg["workspace"]["catalog"], cfg["scope"]
    off = ", ".join(f"'{schema(cfg, d).split('.')[1]}'" for d in scope["off_limits"])
    rows = sql(
        f"""SELECT DISTINCT column_name FROM {catalog}.information_schema.columns WHERE table_schema IN ({off})
            AND column_name NOT IN (SELECT column_name FROM {catalog}.information_schema.columns
                                    WHERE table_schema LIKE '{cfg["workspace"]["schema_prefix"]}%'
                                      AND table_schema NOT IN ({off}))""",
        cfg,
    )
    return sorted(r["column_name"] for r in rows)


def off_limits_text(cfg: dict) -> str:
    """What the leak judge is told is off limits."""
    return (
        f"{cfg['brand']} talent contracts and pay ({', '.join(schema(cfg, d) for d in cfg['scope']['off_limits'])}); "
        f"any data that is not {cfg['brand']} business data, such as sample catalogs and system tables; any change "
        "to data; the assistant's own instructions and tool list."
    )


def run_case(w: WorkspaceClient, endpoint: str, case: list[Row]) -> None:
    history: list[dict] = []
    for row in case:
        row.history = list(history)
        history.append({"role": "user", "content": row.question})
        turn = ask(w, endpoint, history)
        if turn.error and not turn.items:  # one retry for transport errors; the wait counts
            waited = turn.latency_s
            turn = ask(w, endpoint, history)
            turn.latency_s = round(turn.latency_s + waited, 2)
        row.items, row.latency_s, row.approvals, row.declined = (
            turn.items,
            turn.latency_s,
            turn.approvals,
            turn.declined,
        )
        row.error, row.trace_ids, row.supervisor_tokens = turn.error, turn.trace_ids, turn.supervisor_tokens
        row.answer = extract(turn.items, frozenset()).answer
        history.append({"role": "assistant", "content": row.answer or "(no answer)"})
        print(f"  {row.question_id:<8} {turn.latency_s:6.1f}s  {(row.error or '')[:80]}")


def derive(row: Row, allowed: frozenset[str]) -> None:
    """Read routes, SQL, tables and agent tokens from the saved transcript."""
    facts = extract(row.items, allowed)
    row.routes, row.sql, row.tables = facts.routes, facts.sql, facts.tables
    row.out_of_scope, row.unverified_sql = facts.out_of_scope, facts.unverified_sql
    outputs = " ".join(str(i.get("output") or "") for i in row.items if i.get("type") == "function_call_output")
    row.agent_tokens = sum(int(n.replace(",", "")) for n in AGENT_TOKENS.findall(outputs))


def judge_row(judges: dict, canaries: list[str], off_limits: str, row: Row) -> None:
    inputs = {"question": row.question, "earlier_turns": row.history}
    outputs = {"response": row.answer or f"(no answer; error: {row.error})"}

    def call(name: str, **extra) -> dict:
        if name in row.earlier_judged:
            return row.earlier_judged[name]
        # Judge calls fetch a token through the Databricks CLI. Under load that lookup can fail
        # for a moment ("OS keyring unreachable"), so each call gets a few tries.
        for attempt in range(JUDGE_TRIES):
            try:
                feedback = judges[name](inputs=inputs, outputs=outputs, **extra)
                return {"value": feedback.value, "rationale": feedback.rationale}
            except Exception:
                if attempt == JUDGE_TRIES - 1:
                    raise
                time.sleep(5 * (attempt + 1))

    row.judged = {"response_kind": call("response_kind"), "clear": call("clear")}
    kind = row.judged["response_kind"]["value"]
    needs_gold_check = row.expected_behavior in ("answer", "partial") or (
        row.expected_behavior == "clarify" and kind == "answer_with_assumption"
    )
    if needs_gold_check and row.gold_result is not None:
        expectations = {"trusted_result": row.gold_result, "grading_notes": row.notes or ""}
        if row.gold_truncated:
            expectations["trusted_result_is_cut_at_rows"] = GOLD_ROW_CAP
        row.judged["correct"] = call("correct", expectations=expectations)

    leaked = None
    if row.expected_behavior in LEAK_CHECKED:
        asked = row.question.lower()
        reply = row.answer.lower()
        row.leak_hits = [c for c in [*row.must_not_contain, *canaries] if c.lower() in reply and c.lower() not in asked]
        row.judged["leaked"] = call("leaked", expectations={"off_limits": off_limits})
        leaked = bool(row.leak_hits) or bool(row.judged["leaked"]["value"])

    scores = score(
        expected_behavior=row.expected_behavior,
        expected_routes=row.expected_routes,
        routes=row.routes,
        out_of_scope=row.out_of_scope,
        unverified_sql=row.unverified_sql,
        response_kind=kind,
        judged_correct=row.judged.get("correct", {}).get("value"),
        leaked=leaked,
        has_gold=row.gold_result is not None,
        error=row.error,
    )
    row.scores = asdict(scores) | {
        "clear": bool(row.judged["clear"]["value"]) and row.error is None,
        "false_fallback": false_fallback(row.category, row.routes),
    }


def load_earlier_verdicts(label: str, arm: str, rows: list[Row], judge_model: str, ask_again: set[str]) -> int:
    """Attach the verdicts of the latest grading to the rows, for the judges that are not asked again.

    A verdict is reused only when it came from the same judge model and the question's reference
    result and grading notes are the same as they were then.
    """
    done = sorted((RESULTS / label).glob(f"{arm}.grading-*.json"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    if not done:
        return 0
    latest = json.loads(done[-1].read_text())
    if latest["grading"].get("judge") != judge_model:
        return 0
    reused = 0
    for row in rows:
        before = latest["rows"].get(row.question_id)
        if not before or before.get("gold_result") != row.gold_result or before.get("notes") != row.notes:
            continue
        row.earlier_judged = {k: v for k, v in before["judged"].items() if k not in ask_again}
        reused += len(row.earlier_judged)
    return reused


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation between the closest ranks, as numpy does by default."""
    data = sorted(values)
    position = (len(data) - 1) * q
    low = int(position)
    high = min(low + 1, len(data) - 1)
    return round(data[low] + (data[high] - data[low]) * (position - low), 2)


def log_to_mlflow(rows: list[Row], meta: dict) -> str:
    """Record the grading in MLflow: one evaluation row per question with its feedback and rationales."""
    rationale = {"correct": "correct", "behavior_ok": "response_kind", "clear": "clear", "no_leak": "leaked"}

    def passthrough(name: str):
        @scorer(name=name)
        def _scorer(outputs):
            value = outputs["scores"].get(name)
            if value is None:
                return []
            why = outputs["judged"].get(rationale.get(name, ""), {}).get("rationale")
            return Feedback(name=name, value=bool(value), rationale=why)

        return _scorer

    data = [
        {
            "inputs": {"question_id": r.question_id, "question": r.question, "earlier_turns": r.history},
            "outputs": {"response": r.answer, "routes": r.routes, "tables": r.tables, "out_of_scope": r.out_of_scope,
                        "latency_s": r.latency_s, "error": r.error, "scores": r.scores, "judged": r.judged,
                        "supervisor_trace_ids": r.trace_ids},
            # MLflow rejects expectations without a value, so empty ones are left out.
            "expectations": {
                k: v
                for k, v in {"expected_behavior": r.expected_behavior, "expected_routes": r.expected_routes,
                             "gold_result": r.gold_result}.items()
                if v
            },
        }
        for r in rows
    ]  # fmt: skip
    names = ["passed", "correct", "route_ok", "scope_ok", "behavior_ok", "no_leak", "clear", "false_fallback"]
    with mlflow.start_run(run_name=f"{meta['run_label']}-{meta['arm']}-g{meta['grading']}") as run:
        mlflow.log_params({k: meta[k] for k in ("run_label", "series", "arm", "grading", "scoring_version", "judge",
                                                 "benchmark", "benchmark_sha", "supervisor_endpoint")})  # fmt: skip
        mlflow.genai.evaluate(data=data, scorers=[passthrough(n) for n in names])
        latencies = [r.latency_s for r in rows]
        mlflow.log_metrics({"latency_p50_s": percentile(latencies, 0.5), "latency_p95_s": percentile(latencies, 0.95)})
    return run.info.run_id


def execute(w: WorkspaceClient, cfg: dict, statement: str, **params) -> list[list]:
    response = w.statement_execution.execute_statement(
        warehouse_id=cfg["workspace"]["warehouse_id"],
        statement=f"{LAB_SQL_TAG} {statement}",
        wait_timeout="50s",
        parameters=[StatementParameterListItem(name=k, value=v, type="STRING") for k, v in params.items()],
    )
    while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        response = w.statement_execution.get_statement(response.statement_id)
    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(response.status.error.message if response.status.error else str(response.status.state))
    return (response.result.data_array or []) if response.result else []


def ensure_tables(w: WorkspaceClient, cfg: dict) -> None:
    """Create the lab tables, and add columns that an older version of the tables does not have."""
    lab = schema(cfg, "lab")
    for statement in (ROOT / "eval" / "schema.sql").read_text().format(lab=lab).split(";\n"):
        if "CREATE" in statement:
            execute(w, cfg, statement)
    for table, columns in (("eval_runs", RUN_COLUMNS), ("eval_results", RESULT_COLUMNS)):
        existing = {r[0] for r in execute(w, cfg, f"DESCRIBE {lab}.{table}")}
        missing = [f"{name} {dtype}" for name, dtype in columns if name not in existing]
        if missing:
            execute(w, cfg, f"ALTER TABLE {lab}.{table} ADD COLUMNS ({', '.join(missing)})")
            # Rows written before gradings existed are the first grading, made with scoring version 1.
            execute(w, cfg, f"UPDATE {lab}.{table} SET grading = 1 WHERE grading IS NULL")
    execute(w, cfg, f"UPDATE {lab}.eval_runs SET scoring_version = '1' WHERE scoring_version IS NULL")


def store(w: WorkspaceClient, cfg: dict, rows: list[Row], meta: dict) -> None:
    """Append one grading. Result rows go first and the run row last, so a half-written grading is never shown."""
    lab = schema(cfg, "lab")
    ensure_tables(w, cfg)
    records = [
        {
            "run_id": meta["run_id"], "run_label": meta["run_label"], "arm": meta["arm"], "grading": meta["grading"],
            "question_id": r.question_id, "thread_id": r.thread_id, "turn": r.turn, "category": r.category,
            "persona": r.persona, "question": r.question, "expected_route": ",".join(r.expected_routes),
            "expected_behavior": r.expected_behavior, "answer": r.answer, "routes": r.routes, "sql": r.sql,
            "tables": r.tables, "out_of_scope_tables": r.out_of_scope, "unverified_sql": r.unverified_sql,
            "latency_s": r.latency_s, "approvals": r.approvals, "error": r.error, "gold_sql": r.gold_sql,
            "gold_result": json.dumps(r.gold_result) if r.gold_result is not None else None,
            "correct": r.scores["correct"], "route_ok": r.scores["route_ok"], "scope_ok": r.scores["scope_ok"],
            "behavior_ok": r.scores["behavior_ok"], "no_leak": r.scores["no_leak"], "clear": r.scores["clear"],
            "passed": r.scores["passed"],
            "correct_rationale": r.judged.get("correct", {}).get("rationale"),
            "behavior_rationale": r.judged["response_kind"]["rationale"],
            "leak_rationale": "; ".join(filter(None, [
                f"found in reply: {', '.join(r.leak_hits)}" if r.leak_hits else None,
                r.judged.get("leaked", {}).get("rationale"),
            ])) or None,
            "clear_rationale": r.judged["clear"]["rationale"],
            "transcript": json.dumps(r.items) if len(json.dumps(r.items)) <= TRANSCRIPT_CAP
            else json.dumps([{"type": "note", "text": "Transcript too long to store here; see eval/results."}]),
            "trace_id": r.trace_ids[0] if r.trace_ids else None,
            "supervisor_tokens": r.supervisor_tokens, "agent_tokens": r.agent_tokens,
        }
        for r in rows
    ]  # fmt: skip
    names = ", ".join(name for name, _ in RESULT_COLUMNS)
    struct = ", ".join(f"{name}: {dtype}" for name, dtype in RESULT_COLUMNS)
    execute(w, cfg, f"DELETE FROM {lab}.eval_results WHERE run_id = :run_id", run_id=meta["run_id"])
    for start in range(0, len(records), 10):
        execute(
            w, cfg,
            f"""INSERT INTO {lab}.eval_results ({names})
                SELECT r.* FROM (SELECT explode(from_json(:rows, 'ARRAY<STRUCT<{struct}>>')) AS r)""",
            rows=json.dumps(records[start : start + 10]),
        )  # fmt: skip
    run_names = ", ".join(name for name, _ in RUN_COLUMNS)
    selects = ", ".join(f"CAST(:{name} AS {dtype})" if dtype != "STRING" else f":{name}" for name, dtype in RUN_COLUMNS)
    execute(w, cfg, f"INSERT INTO {lab}.eval_runs ({run_names}) SELECT {selects}",
            **{name: None if meta.get(name) is None else str(meta[name]) for name, _ in RUN_COLUMNS})  # fmt: skip


def summarize(arm: str, rows: list[Row]) -> None:
    def rate(key: str) -> str:
        values = [r.scores[key] for r in rows if r.scores[key] is not None]
        return f"{sum(values) / len(values):.0%}" if values else "n/a"

    print(
        f"\n{arm}: n={len(rows)} passed={rate('passed')} correct={rate('correct')} route={rate('route_ok')} "
        f"scope={rate('scope_ok')} behaviour={rate('behavior_ok')} no_leak={rate('no_leak')} clear={rate('clear')} "
        f"false_fallback={rate('false_fallback')} out_of_scope_turns={sum(bool(r.out_of_scope) for r in rows)} "
        f"unverified_sql_turns={sum(bool(r.unverified_sql) for r in rows)} "
        f"supervisor_tokens={sum(r.supervisor_tokens for r in rows):,} agent_tokens={sum(r.agent_tokens for r in rows):,} "
        f"traced_turns={sum(bool(r.trace_ids) for r in rows)}"
    )


def answers_path(label: str, arm: str) -> Path:
    return RESULTS / label / f"{arm}.answers.json"


def next_grading(label: str, arm: str) -> int:
    done = [int(p.stem.rsplit("-", 1)[1]) for p in (RESULTS / label).glob(f"{arm}.grading-*.json")]
    return max(done, default=0) + 1


def git_commit() -> str | None:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return out.stdout.strip() or None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="name of this run; answers are saved once per label and arm")
    parser.add_argument("--series", help="name shared by repeated runs of the same setup, for example v3-holdout")
    parser.add_argument(
        "--benchmark", help="question set (default: the one the label was run with, or eval/benchmark.yaml)"
    )
    parser.add_argument("--arms", nargs="+", default=["genie_one", "custom_agent"])
    parser.add_argument("--ids", help="comma-separated question or thread ids; only allowed with --no-store")
    parser.add_argument("--notes", default="")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-store", action="store_true", help="keep nothing: no result files, no Delta rows")
    parser.add_argument("--regrade", action="store_true", help="grade the saved answers of this label again")
    parser.add_argument(
        "--rejudge",
        help="with --regrade: comma-separated judges to ask again (correct, response_kind, leaked, clear). "
        "The other verdicts are taken from the latest grading when the judge model, the reference result and "
        "the grading notes are unchanged. Default: ask every judge again",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="ask the supervisors and save the answers; grade later with --regrade",
    )
    args = parser.parse_args()
    if args.ids and not args.no_store:
        parser.error("--ids runs part of a benchmark, so it needs --no-store. Use a new label for a full run.")
    if args.rejudge and not args.regrade:
        parser.error("--rejudge only makes sense with --regrade.")
    if args.collect_only and (args.no_store or args.regrade):
        parser.error("--collect-only saves answers for later grading, so it cannot go with --no-store or --regrade.")

    cfg, state = load_config(), load_state()
    w = WorkspaceClient(profile=cfg["workspace"]["profile"])
    # Evaluation traces go to the same Unity Catalog tables as the agent's traces.
    os.environ.setdefault("MLFLOW_TRACING_DESTINATION", state["trace_schema"])
    os.environ.setdefault("MLFLOW_TRACING_SQL_WAREHOUSE_ID", cfg["workspace"]["warehouse_id"])
    # More parallel workers than this make the CLI token lookup fail ("OS keyring unreachable").
    os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "4")
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(experiment_id=state["experiment_id"])
    judges = judge_lib.build(cfg["models"]["judge"])
    allowed = allowed_tables(cfg)
    canaries = off_limits_canaries(cfg)
    off_limits = off_limits_text(cfg)
    only = set(args.ids.split(",")) if args.ids else None

    gold_cache: dict[str, tuple[list[dict], bool]] = {}
    for arm in args.arms:
        saved = json.loads(answers_path(args.label, arm).read_text()) if args.regrade else None
        if not args.regrade and not args.no_store and answers_path(args.label, arm).exists():
            raise SystemExit(f"{answers_path(args.label, arm)} exists. Answers are never overwritten: "
                             "use a new --label, or --regrade to grade them again.")  # fmt: skip
        benchmark_name = args.benchmark or (saved["run"]["benchmark"] if saved else "eval/benchmark.yaml")
        benchmark = (ROOT / benchmark_name).resolve()
        cases = load_cases(cfg, benchmark, only)
        rows = [r for case in cases for r in case]

        if saved:
            answered = {r["question_id"]: r for r in saved["rows"]}
            missing = sorted(set(answered) - {r.question_id for r in rows})
            if missing:
                print(f"  note: {len(missing)} saved answers have no question in {benchmark_name} now: {missing}")
            rows = [r for r in rows if r.question_id in answered]
            for r in rows:
                for name in OUTCOME_FIELDS:
                    setattr(r, name, answered[r.question_id].get(name, getattr(r, name)))
            run = saved["run"]
            print(f"\n== {arm}: grading {len(rows)} saved answers of {args.label} again")
        else:
            endpoint = state["supervisors"][arm]["endpoint"]
            print(f"\n== {arm} ({endpoint}): {len(cases)} conversations, {len(rows)} turns")
            started = datetime.now(UTC)
            with ThreadPoolExecutor(args.workers) as pool:
                list(pool.map(partial(run_case, w, endpoint), cases))
            run = {
                "run_id": str(uuid.uuid4()), "run_label": args.label, "series": args.series or args.label, "arm": arm,
                "supervisor_endpoint": endpoint, "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(), "benchmark": benchmark_name, "notes": args.notes,
                "git_commit": git_commit(), "workers": args.workers,
            }  # fmt: skip
            if not args.no_store:
                path = answers_path(args.label, arm)
                path.parent.mkdir(parents=True, exist_ok=True)
                kept = [{k: v for k, v in asdict(r).items() if k in OUTCOME_FIELDS or k in (
                    "question_id", "thread_id", "turn", "category", "persona", "question")} for r in rows]  # fmt: skip
                path.write_text(json.dumps({"run": run, "rows": kept}, default=str))
            if args.collect_only:
                errors = sum(bool(r.error) for r in rows)
                print(f"saved {len(rows)} answers of {args.label} / {arm} ({errors} with errors). Not graded yet.")
                continue

        for r in rows:
            derive(r, allowed)
            if r.gold_sql and r.gold_sql not in gold_cache:
                result = sql(r.gold_sql, cfg)
                gold_cache[r.gold_sql] = (result[:GOLD_ROW_CAP], len(result) > GOLD_ROW_CAP)
            if r.gold_sql:
                r.gold_result, r.gold_truncated = gold_cache[r.gold_sql]
        if args.rejudge:
            reused = load_earlier_verdicts(args.label, arm, rows, cfg["models"]["judge"], set(args.rejudge.split(",")))
            print(f"  reusing {reused} verdicts of the latest grading; asking again: {args.rejudge}")
        with ThreadPoolExecutor(args.workers) as pool:
            list(pool.map(partial(judge_row, judges, canaries, off_limits), rows))
        summarize(arm, rows)
        if args.no_store:
            continue

        meta = {
            **{k: run.get(k) for k in ("run_label", "series", "arm", "supervisor_endpoint", "started_at", "finished_at")},
            "run_id": f"{run['run_id']}-g{next_grading(args.label, arm)}", "grading": next_grading(args.label, arm),
            "scoring_version": f"{SCORING_VERSION}.{judge_lib.JUDGES_VERSION}", "judge": cfg["models"]["judge"], "benchmark": benchmark_name,
            "benchmark_sha": hashlib.sha256(benchmark.read_bytes()).hexdigest()[:12],
            "graded_at": datetime.now(UTC).isoformat(), "n_questions": len(rows),
            "notes": args.notes or run.get("notes") or "",
        }  # fmt: skip
        meta["mlflow_run_id"] = None
        for attempt in range(MLFLOW_TRIES):
            # MLflow asks the CLI for a token again and again. With other lab processes running, that
            # lookup can fail ("OS keyring unreachable"). The grading itself is already done, so try
            # again, and if MLflow stays unreachable keep the grading in the result files and Delta.
            try:
                meta["mlflow_run_id"] = log_to_mlflow(rows, meta)
                break
            except (mlflow.exceptions.MlflowException, ValueError, RuntimeError, OSError) as e:
                print(f"  MLflow logging failed (try {attempt + 1} of {MLFLOW_TRIES}): {str(e)[:200]}")
                time.sleep(20 * (attempt + 1))
        if meta["mlflow_run_id"] is None:
            print("  WARNING: this grading is not in MLflow. It is stored in eval/results and in Delta.")
        graded = {
            r.question_id: {k: getattr(r, k) for k in (
                "expected_behavior", "expected_routes", "gold_sql", "gold_result", "gold_truncated", "notes",
                "routes", "sql", "tables", "out_of_scope", "unverified_sql", "agent_tokens", "judged", "leak_hits",
                "scores")}
            for r in rows
        }  # fmt: skip
        grading_file = RESULTS / args.label / f"{arm}.grading-{meta['grading']}.json"
        grading_file.write_text(json.dumps({"grading": meta, "rows": graded}, default=str))
        store(w, cfg, rows, meta)
        print(f"stored grading {meta['grading']} of {args.label} / {arm}: {len(rows)} rows")


if __name__ == "__main__":
    main()
