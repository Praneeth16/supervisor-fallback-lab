"""Fail when an evaluation question asks for the same thing as something the agents were given.

  python scripts/check_overlap.py

An agent that has seen a question, or the SQL that answers it, is not being tested on that
question. This compares every benchmark question and its reference SQL with the material the
agents hold: the example questions, example SQL, sample questions and built-in benchmark questions
of the two Genie Agents, and the routing examples of the supervisors.

Two things count as the same: reference SQL that is nearly identical, or question wording that is
nearly identical. The thresholds are deliberately cautious; a pair it flags needs a human look,
and a pair it passes can still be the same idea in different words.
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "supervisors"))

BENCHMARKS = sorted((ROOT / "eval").glob("benchmark*.yaml"))
GENIE_SPECS = sorted((ROOT / "genie").glob("*.yaml"))
SQL_THRESHOLD = 0.8
TEXT_THRESHOLD = 0.6
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "for",
        "to",
        "by",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "we",
        "our",
        "us",
        "you",
        "your",
        "i",
        "me",
        "my",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "what",
        "which",
        "who",
        "how",
        "many",
        "much",
        "with",
        "from",
        "at",
        "as",
        "be",
        "been",
        "has",
        "have",
        "had",
        "per",
        "pls",
        "please",
        "vs",
        "can",
        "could",
        "give",
        "show",
        "tell",
        "list",
        "get",
        "there",
        "right",
        "now",
    ]
)


def sql_tokens(sql: str) -> frozenset[str]:
    """Tokens of a query with literals kept, so the same query over another month is not the same."""
    text = re.sub(r"--[^\n]*", " ", sql.lower())
    return frozenset(re.findall(r"[a-z_][a-z0-9_]*|\d+(?:\.\d+)?|'[^']*'", text))


def text_tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOPWORDS)


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def evaluation_items() -> list[dict]:
    items = []
    for path in BENCHMARKS:
        spec = yaml.safe_load(path.read_text())
        for q in spec.get("questions", []):
            items.append({"where": f"{path.name}:{q['id']}", "text": q["ask"], "sql": q.get("gold")})
        for thread in spec.get("threads", []):
            for n, turn in enumerate(thread["turns"], 1):
                items.append({"where": f"{path.name}:{thread['id']}.{n}", "text": turn["ask"], "sql": turn.get("gold")})
    return items


def agent_items() -> list[dict]:
    from create import EXAMPLES

    items = [{"where": "supervisors/create.py:EXAMPLES", "text": question, "sql": None} for question, _ in EXAMPLES]
    for path in GENIE_SPECS:
        spec = yaml.safe_load(path.read_text())
        for kind in ("examples", "benchmarks"):
            for entry in spec.get(kind, []):
                items.append({"where": f"{path.name}:{kind}", "text": entry["question"], "sql": entry.get("sql")})
        for question in spec.get("sample_questions", []):
            items.append({"where": f"{path.name}:sample_questions", "text": question, "sql": None})
    return items


def find_overlaps() -> list[str]:
    found = []
    for agent in agent_items():
        for question in evaluation_items():
            by_sql = similarity(sql_tokens(agent["sql"] or ""), sql_tokens(question["sql"] or ""))
            by_text = similarity(text_tokens(agent["text"]), text_tokens(question["text"]))
            if by_sql >= SQL_THRESHOLD or by_text >= TEXT_THRESHOLD:
                found.append(
                    f'{agent["where"]}: "{agent["text"]}"\n    same as {question["where"]}: "{question["text"]}" '
                    f"(sql {by_sql:.2f}, wording {by_text:.2f})"
                )
    return found


def main():
    overlaps = find_overlaps()
    for line in overlaps:
        print(f"- {line}")
    n_eval, n_agent = len(evaluation_items()), len(agent_items())
    print(f"{n_eval} evaluation questions checked against {n_agent} agent examples: {len(overlaps)} overlaps")
    if overlaps:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
