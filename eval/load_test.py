"""Send questions to each supervisor at several levels of concurrency and record time and errors.

  python eval/load_test.py --levels 1 4 12

The benchmark asks four questions at a time. This test shows what happens to response time and
errors when more people ask at once. It uses questions that need the fallback, taken from the
holdout set. Answers are not graded here: the test records whether an answer came back, how long
it took and which agents were used. Arms and levels run one after the other.

Results are kept in eval/results/load/<test_id>.json and shown by eval/report.py.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "app" / "backend")]

from labconfig import load_config, load_state
from labcore.parse import extract
from labcore.supervisor import ask

ARMS = ("genie_one", "custom_agent")
FALLBACK_ROUTES = {"genie_one", "fallback_agent"}


def percentile(values: list[float], q: float) -> float:
    data = sorted(values)
    position = (len(data) - 1) * q
    low = int(position)
    high = min(low + 1, len(data) - 1)
    return round(data[low] + (data[high] - data[low]) * (position - low), 1)


def fallback_questions(benchmark: Path) -> list[str]:
    """Single questions that expect an answer and may be answered by a fallback."""
    spec = yaml.safe_load(benchmark.read_text())
    return [
        q["ask"].strip()
        for q in spec.get("questions", [])
        if q.get("behavior", "answer") == "answer" and FALLBACK_ROUTES & set(q.get("routes", []))
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", nargs="+", type=int, default=[1, 4, 12], help="requests in flight at once")
    parser.add_argument("--benchmark", default="eval/benchmark_holdout.yaml")
    parser.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS)
    args = parser.parse_args()

    cfg, state = load_config(), load_state()
    w = WorkspaceClient(profile=cfg["workspace"]["profile"])
    questions = fallback_questions(ROOT / args.benchmark)
    if not questions:
        raise SystemExit(f"No fallback questions in {args.benchmark}.")
    test_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    levels = []
    for arm in args.arms:
        endpoint = state["supervisors"][arm]["endpoint"]
        for level in args.levels:
            count = max(6, 2 * level)
            batch = [questions[i % len(questions)] for i in range(count)]

            def one(question: str, endpoint: str = endpoint) -> dict:
                turn = ask(w, endpoint, [{"role": "user", "content": question}])
                facts = extract(turn.items, frozenset())
                return {
                    "question": question, "latency_s": turn.latency_s, "error": turn.error,
                    "answered": bool(facts.answer) and not turn.error, "routes": facts.routes,
                }  # fmt: skip

            started_at, started = datetime.now(UTC).isoformat(), time.monotonic()
            with ThreadPoolExecutor(level) as pool:
                rows = list(pool.map(one, batch))
            wall = round(time.monotonic() - started, 1)
            times = [r["latency_s"] for r in rows]
            summary = {
                "arm": arm, "concurrency": level, "requests": count, "answered": sum(r["answered"] for r in rows),
                "errors": sum(bool(r["error"]) for r in rows), "p50_s": percentile(times, 0.5),
                "p95_s": percentile(times, 0.95), "max_s": round(max(times), 1), "wall_s": wall,
                "started_at": started_at, "finished_at": datetime.now(UTC).isoformat(),
            }  # fmt: skip
            print({k: v for k, v in summary.items() if not k.endswith("_at")})
            for r in rows:
                if r["error"]:
                    print(f"    error: {r['error'][:160]}")
            levels.append({**summary, "rows": rows})

    out = ROOT / "eval" / "results" / "load"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{test_id}.json").write_text(
        json.dumps({"test_id": test_id, "benchmark": args.benchmark, "levels": levels}, indent=1)
    )
    print(f"stored eval/results/load/{test_id}.json")


if __name__ == "__main__":
    main()
