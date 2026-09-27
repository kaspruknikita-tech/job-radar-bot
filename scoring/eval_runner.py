from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path

from . import score_vacancy

logger = logging.getLogger(__name__)

EVAL_FILE = Path("evals/scoring_v1.csv")
TIERS = ["S", "A", "B", "C"]


def run_eval() -> None:
    if not EVAL_FILE.exists():
        print(f"Eval file not found: {EVAL_FILE}")
        return

    rows = list(csv.DictReader(EVAL_FILE.open(encoding="utf-8")))
    if not rows:
        print("Eval file is empty.")
        return

    correct = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    discrepancies = []

    for row in rows:
        vacancy = {
            "id": int(row["vacancy_id"]),
            "title": row.get("title", ""),
            "company": row.get("company", ""),
            "description": row.get("description", ""),
            "location": row.get("location", ""),
        }
        result = score_vacancy(vacancy)
        expected = row["expected_tier"]

        confusion[expected][result.tier] += 1

        if result.tier == expected:
            correct += 1
        else:
            discrepancies.append({
                "vacancy_id": row["vacancy_id"],
                "title": row.get("title", "")[:50],
                "expected": expected,
                "got": result.tier,
                "score": result.score,
                "reason": result.reason,
            })

    total = len(rows)
    accuracy = correct / total if total else 0

    print(f"\nAccuracy: {correct}/{total} = {accuracy:.1%}")
    print("\nConfusion matrix (rows=expected, cols=got):")
    header = f"{'':8}" + "".join(f"{t:6}" for t in TIERS)
    print(header)
    for exp in TIERS:
        row_str = f"{exp:8}" + "".join(f"{confusion[exp][got]:6}" for got in TIERS)
        print(row_str)

    if discrepancies:
        print(f"\nDiscrepancies ({len(discrepancies)}):")
        for d in discrepancies:
            print(f"  [{d['vacancy_id']}] {d['title']}: expected={d['expected']} got={d['got']} score={d['score']}")
            print(f"    {d['reason']}")
    else:
        print("\nNo discrepancies.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_eval()
