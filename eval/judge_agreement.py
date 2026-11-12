"""Measure how far a second judge model and a human agree with the benchmark's judges.

  python eval/judge_agreement.py --label v3-holdout-r1            # sample 30 turns, ask the second judge
  python eval/judge_agreement.py --label v3-holdout-r1            # run again after a person filled the sheet

The benchmark's verdicts come from one judge model. This script takes a sample of graded turns and:

  1. asks a second judge model from another family (lab.yaml: models.second_judge) the same questions
  2. writes eval/results/<label>/human_review.csv for a person to fill in. The sheet shows the
     question, the reference result and the answer, and not what the judges said
  3. when the sheet has labels, compares them with both judge models

Agreement is the share of turns with the same verdict. Kappa corrects that share for agreement by
chance: 1 is perfect, 0 is no better than chance. The result is written to
eval/results/<label>/agreement.json. The sheet is never overwritten, because it may hold labels.
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "app" / "backend"), str(ROOT / "eval")]

RESULTS = ROOT / "eval" / "results"
ARMS = ("genie_one", "custom_agent")
JUDGES = ("correct", "response_kind", "leaked")
HUMAN_COLUMNS = {"correct": "human_correct", "response_kind": "human_response_kind", "leaked": "human_leaked"}
SHEET_COLUMNS = [
    "arm", "question_id", "expected_behavior", "question", "earlier_turns", "reference_result", "grading_notes",
    "answer", "human_correct", "human_response_kind", "human_leaked", "comment",
]  # fmt: skip
TEXT_CAP = 6000


def agreement(pairs: list[tuple]) -> dict:
    """Share of equal pairs and Cohen's kappa. Kappa is None when it is undefined (one label only)."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "agreement": None, "kappa": None}
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    by_chance = sum(left[label] * right[label] for label in left.keys() | right.keys()) / (n * n)
    kappa = None if by_chance == 1 else round((observed - by_chance) / (1 - by_chance), 3)
    return {"n": n, "agreement": round(observed, 3), "kappa": kappa}


def pick(pool: list[dict], n: int, seed: int) -> list[dict]:
    """A seeded sample that takes turns from every expected behaviour in rotation."""
    groups: dict[str, list[dict]] = {}
    for row in pool:
        groups.setdefault(row["expected_behavior"], []).append(row)
    rng = random.Random(seed)
    for rows in groups.values():
        rng.shuffle(rows)
    picked = []
    while len(picked) < n and any(groups.values()):
        for behavior in sorted(groups):
            if groups[behavior] and len(picked) < n:
                picked.append(groups[behavior].pop())
    return picked


def parse_label(name: str, value: str):
    """Read one cell of the sheet. Empty means not labelled."""
    text = value.strip().lower()
    if not text:
        return None
    if name == "response_kind":
        return text
    if text in ("true", "yes", "y", "1"):
        return True
    if text in ("false", "no", "n", "0"):
        return False
    return None


def load_pool(label: str) -> list[dict]:
    pool = []
    for arm in ARMS:
        folder = RESULTS / label
        gradings = sorted(folder.glob(f"{arm}.grading-*.json"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        if not gradings:
            continue
        answers = {r["question_id"]: r for r in json.loads((folder / f"{arm}.answers.json").read_text())["rows"]}
        graded = json.loads(gradings[-1].read_text())
        for qid, g in graded["rows"].items():
            a = answers[qid]
            pool.append({
                "arm": arm, "question_id": qid, "expected_behavior": g["expected_behavior"],
                "question": a["question"], "history": a.get("history") or [], "answer": a.get("answer") or "",
                "error": a.get("error"), "gold_result": g.get("gold_result"), "gold_truncated": g.get("gold_truncated"),
                "notes": g.get("notes"), "first": {k: v["value"] for k, v in g["judged"].items() if k in JUDGES},
                "grading": graded["grading"]["grading"],
            })  # fmt: skip
    return pool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--n", type=int, default=30, help="turns to sample")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    import judges as judge_lib
    import mlflow
    from labconfig import load_config, load_state
    from run_eval import GOLD_ROW_CAP, JUDGE_TRIES, off_limits_text

    cfg, state = load_config(), load_state()
    pool = load_pool(args.label)
    if not pool:
        raise SystemExit(f"No graded answers for label {args.label} in eval/results.")
    sheet = RESULTS / args.label / "human_review.csv"
    human: dict[tuple[str, str], dict] = {}
    if sheet.exists():
        with sheet.open(newline="", encoding="utf-8") as handle:
            human = {(r["arm"], r["question_id"]): r for r in csv.DictReader(handle)}
        sample = [r for r in pool if (r["arm"], r["question_id"]) in human]
        print(f"Using the {len(sample)} turns of the existing sheet {sheet.relative_to(ROOT)}")
    else:
        sample = pick(pool, args.n, args.seed)

    os.environ.setdefault("MLFLOW_TRACING_DESTINATION", state["trace_schema"])
    os.environ.setdefault("MLFLOW_TRACING_SQL_WAREHOUSE_ID", cfg["workspace"]["warehouse_id"])
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(experiment_id=state["experiment_id"])
    second_model = cfg["models"]["second_judge"]
    judges = judge_lib.build(second_model)
    off_limits = off_limits_text(cfg)

    def second(row: dict) -> None:
        inputs = {"question": row["question"], "earlier_turns": row["history"]}
        outputs = {"response": row["answer"] or f"(no answer; error: {row['error']})"}
        expectations = {"trusted_result": row["gold_result"], "grading_notes": row["notes"] or ""}
        if row["gold_truncated"]:
            expectations["trusted_result_is_cut_at_rows"] = GOLD_ROW_CAP
        extra = {"correct": {"expectations": expectations}, "leaked": {"expectations": {"off_limits": off_limits}}}
        row["second"] = {}
        for name in row["first"]:  # the second judge is asked exactly what the first one was asked
            for attempt in range(JUDGE_TRIES):
                try:
                    feedback = judges[name](inputs=inputs, outputs=outputs, **extra.get(name, {}))
                    row["second"][name] = feedback.value
                    break
                except Exception:
                    if attempt == JUDGE_TRIES - 1:
                        raise
                    time.sleep(5 * (attempt + 1))

    with ThreadPoolExecutor(4) as pool_:
        list(pool_.map(second, sample))

    if not sheet.exists():
        with sheet.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
            writer.writeheader()
            for row in sample:
                earlier = " | ".join(f"{m['role']}: {m['content']}" for m in row["history"])
                writer.writerow({
                    "arm": row["arm"], "question_id": row["question_id"], "expected_behavior": row["expected_behavior"],
                    "question": row["question"], "earlier_turns": earlier[:TEXT_CAP],
                    "reference_result": json.dumps(row["gold_result"])[:TEXT_CAP] if row["gold_result"] is not None else "",
                    "grading_notes": row["notes"] or "", "answer": row["answer"][:TEXT_CAP],
                })  # fmt: skip
        print(f"Wrote {sheet.relative_to(ROOT)}. Fill human_correct (true or false), human_response_kind "
              "(answer, answer_with_assumption, clarification, refusal or mixed) and human_leaked (true or false) "
              "where they apply, then run this script again.")  # fmt: skip

    for row in sample:
        cells = human.get((row["arm"], row["question_id"]), {})
        row["human"] = {
            name: value
            for name in JUDGES
            if (value := parse_label(name, cells.get(HUMAN_COLUMNS[name], ""))) is not None
        }

    summary = {}
    for name in JUDGES:
        summary[name] = {
            "first_vs_second": agreement([(r["first"][name], r["second"][name]) for r in sample
                                          if name in r["first"] and name in r["second"]]),
            "first_vs_human": agreement([(r["first"][name], r["human"][name]) for r in sample
                                         if name in r["first"] and name in r["human"]]),
            "second_vs_human": agreement([(r["second"][name], r["human"][name]) for r in sample
                                          if name in r.get("second", {}) and name in r["human"]]),
        }  # fmt: skip
    disagreements = [
        {"arm": r["arm"], "question_id": r["question_id"], "judge": name, "first": r["first"][name], "second": r["second"][name]}
        for r in sample for name in JUDGES
        if name in r["first"] and name in r["second"] and r["first"][name] != r["second"][name]
    ]  # fmt: skip
    out = {
        "label": args.label, "first_judge": cfg["models"]["judge"], "second_judge": second_model,
        "turns": len(sample), "human_labelled_turns": sum(bool(r["human"]) for r in sample),
        "summary": summary, "disagreements": disagreements,
        "rows": [{k: r[k] for k in ("arm", "question_id", "expected_behavior", "grading", "first", "second", "human")}
                 for r in sample],
    }  # fmt: skip
    (RESULTS / args.label / "agreement.json").write_text(json.dumps(out, indent=1))

    print(f"\n{len(sample)} turns of {args.label}. First judge {out['first_judge']}, second judge {second_model}.")
    for name in JUDGES:
        for pair, stats in summary[name].items():
            if stats["n"]:
                print(
                    f"  {name:<14} {pair:<16} n={stats['n']:<3} agreement={stats['agreement']:.0%} kappa={stats['kappa']}"
                )
    for d in disagreements:
        print(f"  differ: {d['arm']} {d['question_id']} {d['judge']}: first={d['first']} second={d['second']}")
    if not out["human_labelled_turns"]:
        print("  No human labels yet.")


if __name__ == "__main__":
    main()
