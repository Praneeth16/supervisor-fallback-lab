"""Run every SQL statement kept in the Genie specs and the benchmark, and report failures.

python scripts/check_sql.py            # all files
python scripts/check_sql.py eval/benchmark.yaml
"""

import sys
from concurrent.futures import ThreadPoolExecutor

import yaml
from labconfig import ROOT, load_config, placeholders, sql

FILES = ["genie/subscribers_revenue.yaml", "genie/content_viewing.yaml", "eval/benchmark.yaml"]


def statements(path: str):
    spec = yaml.safe_load((ROOT / path).read_text())
    for kind in ("examples", "benchmarks"):
        for item in spec.get(kind, []):
            yield f"{path}:{kind}:{item['question'][:50]}", item["sql"]
    for q in spec.get("questions", []):
        if q.get("gold"):
            yield f"{path}:{q['id']}", q["gold"]
    for thread in spec.get("threads", []):
        for n, turn in enumerate(thread["turns"], 1):
            if turn.get("gold"):
                yield f"{path}:{thread['id']}.{n}", turn["gold"]


def main():
    cfg = load_config()
    names = placeholders(cfg)
    todo = [s for path in (sys.argv[1:] or FILES) if (ROOT / path).exists() for s in statements(path)]

    def run(item):
        label, text = item
        try:
            rows = sql(text.format(**names), cfg)
            return label, len(rows), str(rows[0])[:110] if rows else "NO ROWS"
        except (RuntimeError, KeyError, IndexError, ValueError) as e:
            return label, -1, str(e)[:300]

    failed = 0
    with ThreadPoolExecutor(6) as pool:
        for label, n, note in pool.map(run, todo):
            flag = "FAIL" if n < 0 else ("EMPTY" if n == 0 else "ok")
            failed += n <= 0
            print(f"{flag:<5} {label:<70} {n:>4}  {note}")
    print(f"{len(todo)} statements, {failed} need attention")


main()
