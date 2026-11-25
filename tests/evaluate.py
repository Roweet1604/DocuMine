"""Measures search quality: how often the expected file is in the top 5 results.

Needs a filled-in .env and the sample_data files ingested. Run:
  python tests/evaluate.py                 # keyword, vector and hybrid, one after another
  python tests/evaluate.py --mode keyword  # only one method
keyword = full-text only (the search before pgvector); hybrid = what retrieve.search uses now.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from documine import retrieve  # noqa: E402

TOP_K = 5
QUESTIONS_FILE = ROOT / "tests" / "eval_questions.json"
MODES = {
    "keyword": lambda query, k: retrieve.keyword_search(query, k),
    "vector": lambda query, k: retrieve.vector_search(query, k),
    "hybrid": lambda query, k: retrieve.search(query, k),
}


def evaluate(questions: list[dict], search=None, top_k: int = TOP_K) -> dict:
    """Return {total, hits, failures}. A hit means expected_filename is among the top_k results."""
    search = search or retrieve.search
    failures = []
    for q in questions:
        filenames = [r["filename"] for r in search(q["question"], top_k)[:top_k]]
        if q["expected_filename"] not in filenames:
            failures.append({"id": q["id"], "question": q["question"],
                             "expected": q["expected_filename"], "got": filenames})
    return {"total": len(questions), "hits": len(questions) - len(failures), "failures": failures}


def print_report(mode: str, report: dict) -> None:
    total, hits = report["total"], report["hits"]
    print(f"[{mode}] expected file in top {TOP_K}: {hits}/{total} ({hits / total:.0%})")
    for f in report["failures"]:
        got = ", ".join(f["got"]) or "no results"
        print(f"  - Q{f['id']}: {f['question']}\n      expected: {f['expected']}\n      got: {got}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=[*MODES, "all"], default="all")
    args = parser.parse_args()
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    status = 0
    for mode in (MODES if args.mode == "all" else [args.mode]):
        try:
            print_report(mode, evaluate(questions, MODES[mode]))
        except Exception as e:
            print(f"[{mode}] could not run: {e}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
