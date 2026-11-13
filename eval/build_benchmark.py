"""Draft benchmark questions with their reference SQL, using a larger model than the agents.

  python eval/build_benchmark.py --from questions.txt      # your questions, one per line
  python eval/build_benchmark.py --from context --n 12     # the model also drafts the questions
  python eval/build_benchmark.py --from feedback           # chat answers people gave a thumbs up

A benchmark question needs a reference answer, and writing reference SQL by hand is the slow part.
Here the model named under models.gold_builder in lab.yaml reads the same table descriptions the
custom agent has, writes the SQL, and the script runs it. The model never sees what an agent
answered, so the reference is not copied from the thing it is meant to check.

The output is a draft: every question carries `reviewed: false`, and eval/run_eval.py refuses a file
that still has such questions. A person who knows the data reads each question, its SQL and its
result, corrects what is wrong, and sets `reviewed: true`. Only then is it ground truth.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts")]

from labconfig import DOMAINS, load_config, schema, sql

CONTEXT = ROOT / "custom_agent" / "context"
DEFAULT_MODEL = "databricks-gpt-6-astra"
RESULT_ROWS_IN_NOTES = 8
FALLBACK_ROUTES = ["genie_one", "fallback_agent"]

WRITE_SQL = """You write reference SQL for a benchmark of data agents. The SQL must be correct, because
agents are graded against its result.

Rules:
- Use only the tables described below, with fully qualified names.
- One Databricks SQL SELECT statement. No comments.
- If the question is ambiguous, pick the most natural reading and say which in "notes".
- If the tables cannot answer the question, set "answerable" to false and explain in "notes".
- "notes" also says what a correct answer must contain, in one or two plain sentences.

Reply with one JSON object and nothing else: {{"answerable": true, "sql": "...", "notes": "..."}}

{rules}

{tables}"""

DRAFT_QUESTIONS = """You draft benchmark questions for data agents that answer business questions with SQL.

Write {n} questions that the tables below can answer. Write them the way people in a media company
ask: short, casual, sometimes with shorthand, without table or column names. Mix easy counts with
questions that need a join, a date range or a ratio. Do not write two questions about the same thing.

Reply with one JSON list of strings and nothing else.

{rules}

{tables}"""


def ask_model(w: WorkspaceClient, model: str, system: str, user: str) -> str:
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    reply = w.api_client.do("POST", f"/serving-endpoints/{model}/invocations", body=body)
    content = reply["choices"][0]["message"]["content"]
    if isinstance(content, list):  # some models answer in parts, with their reasoning in front
        content = "".join(part.get("text", "") for part in content if part.get("type") == "text")
    return content


def parse_json(text: str):
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    raw = match.group(1) if match else text
    start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=0)
    return json.loads(raw[start:].strip())


def context_text(tables_only: set[str] | None = None) -> tuple[str, str]:
    """The table descriptions and data rules the custom agent has (written by scripts/sync_context.py)."""
    if not (CONTEXT / "INDEX.md").is_file():
        raise SystemExit("custom_agent/context is missing. Run scripts/sync_context.py (or make agent) first.")
    docs = []
    for path in sorted((CONTEXT / "tables").glob("*.md")):
        if tables_only is None or path.stem in tables_only:
            docs.append(path.read_text())
    rules = (CONTEXT / "RULES.md").read_text() if (CONTEXT / "RULES.md").is_file() else ""
    return rules, "\n\n".join(docs)


def with_placeholders(statement: str, cfg: dict) -> str:
    """Write schema names as {domain}, the way benchmark files keep SQL, so the file works in any workspace."""
    text = statement.replace("{", "{{").replace("}", "}}")
    for domain in sorted(DOMAINS, key=lambda d: -len(schema(cfg, d))):
        text = re.sub(re.escape(schema(cfg, domain)), "{" + domain + "}", text, flags=re.IGNORECASE)
    return text


def thumbs_up_questions(cfg: dict) -> list[dict]:
    lab = schema(cfg, "lab")
    rows = sql(
        f"""WITH latest AS (
              SELECT turn_id, rating, row_number() OVER (PARTITION BY turn_id, user_email ORDER BY created_at DESC) AS rn
              FROM {lab}.chat_feedback)
            SELECT t.question, max(to_json(t.routes)) AS routes, count(DISTINCT t.user_email) AS people
            FROM {lab}.chat_turns t JOIN latest f ON f.turn_id = t.turn_id AND f.rn = 1 AND f.rating = 'up'
            GROUP BY t.question ORDER BY people DESC, t.question""",
        cfg,
    )
    return [{"ask": r["question"], "routes": json.loads(r["routes"] or "[]"), "source": "feedback"} for r in rows]


def expected_routes(routes: list[str]) -> tuple[list[str], str]:
    """Expected route and category for a question that came from the chat."""
    curated = [r for r in routes if r.startswith("genie:")]
    if curated and not any(r in FALLBACK_ROUTES for r in routes):
        return curated[:1], "curated_subscriber" if "subscribers" in curated[0] else "curated_content"
    return FALLBACK_ROUTES, "long_tail"


def reference(w: WorkspaceClient, cfg: dict, model: str, system: str, question: str) -> dict:
    """Have the model write SQL for one question, run it, and give it one chance to fix an error."""
    prompt = f"Question: {question}"
    for attempt in (1, 2):
        try:
            draft = parse_json(ask_model(w, model, system, prompt))
        except (json.JSONDecodeError, KeyError, IndexError) as error:
            return {"error": f"The model's reply could not be read: {error}"}
        if not draft.get("answerable", True) or not draft.get("sql"):
            return {"answerable": False, "notes": draft.get("notes", "")}
        statement = draft["sql"].strip().rstrip(";")
        try:
            rows = sql(statement, cfg)
            return {"answerable": True, "sql": statement, "notes": draft.get("notes", ""), "rows": rows}
        except RuntimeError as error:
            if attempt == 2:
                return {"error": f"The SQL failed twice: {str(error)[:300]}", "sql": statement}
            prompt = f"Question: {question}\n\nYour SQL failed:\n{statement}\n\nError: {str(error)[:600]}\n\nFix it."
    raise AssertionError("unreachable")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", required=True, help="feedback, context, or a text file of questions")
    parser.add_argument("--n", type=int, default=12, help="how many questions to draft with --from context")
    parser.add_argument("--out", help="file to write. Default: eval/drafts/<source>-<date>.yaml")
    parser.add_argument("--prefix", default="dr", help="prefix of the question ids")
    args = parser.parse_args()

    cfg = load_config()
    model = (cfg.get("models") or {}).get("gold_builder") or DEFAULT_MODEL
    if model == cfg["models"]["agent"]:
        raise SystemExit("models.gold_builder is the agent's own model. Pick a different, larger model.")
    w = WorkspaceClient(profile=cfg["workspace"]["profile"])
    rules, tables = context_text()
    system = WRITE_SQL.format(rules=rules, tables=tables)

    if args.source == "feedback":
        items = thumbs_up_questions(cfg)
        if not items:
            raise SystemExit("No chat answer has a thumbs up yet. Rate some answers in the UI first.")
    elif args.source == "context":
        asked = parse_json(ask_model(w, model, DRAFT_QUESTIONS.format(n=args.n, rules=rules, tables=tables), "Go."))
        items = [{"ask": str(q), "routes": [], "source": "model"} for q in asked][: args.n]
    else:
        lines = Path(args.source).read_text().splitlines()
        items = [
            {"ask": q.strip(), "routes": [], "source": "file"} for q in lines if q.strip() and not q.startswith("#")
        ]

    today = date.today().isoformat()
    questions, skipped = [], []
    for number, item in enumerate(items, start=1):
        result = reference(w, cfg, model, system, item["ask"])
        print(
            f"  {number:>2}/{len(items)} {'ok' if result.get('rows') is not None else 'skipped':<8}{item['ask'][:90]}"
        )
        if result.get("rows") is None:
            skipped.append({"ask": item["ask"], "why": result.get("error") or result.get("notes") or "not answerable"})
            continue
        routes, category = expected_routes(item["routes"]) if item["routes"] else (FALLBACK_ROUTES, "long_tail")
        preview = json.dumps(result["rows"][:RESULT_ROWS_IN_NOTES], default=str)
        questions.append(
            {
                "id": f"{args.prefix}{number:02d}",
                "category": category,
                "persona": "analyst",
                "ask": item["ask"],
                "routes": list(routes),
                "reviewed": False,
                "source": f"{item['source']}, reference SQL drafted by {model} on {today}",
                "notes": f"{result['notes']} Result when drafted ({len(result['rows'])} rows): {preview}"[:1500],
                "gold": with_placeholders(result["sql"], cfg) + "\n",
            }
        )

    out = Path(args.out) if args.out else ROOT / "eval" / "drafts" / f"{Path(args.source).stem}-{today}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Draft benchmark questions. Reference SQL written by {model}, not yet checked by a person.\n"
        "# For each question: read the SQL and the result in notes, fix what is wrong, check routes and category,\n"
        "# then set reviewed: true. eval/run_eval.py refuses this file while any question has reviewed: false.\n"
        "# Same format as eval/benchmark_holdout.yaml.\n\n"
    )
    body = yaml.safe_dump({"questions": questions, "skipped": skipped}, sort_keys=False, width=110, allow_unicode=True)
    out.write_text(header + body)
    print(f"\n{len(questions)} draft questions -> {out} ({len(skipped)} skipped, listed at the end)")
    print("Next: review each one, set reviewed: true, then make eval BENCHMARK=<that file> LABEL=<new label>")


if __name__ == "__main__":
    main()
