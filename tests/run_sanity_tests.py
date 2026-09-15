from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pipeline import run_exam, ensure_imports
from services.exam_store import load_exam
from services.logger import get_logger


log = get_logger("sanity")

CHAPTERS = [1, 2, 3, 4]


def _config(name: str, source: str, book: int, new: int) -> dict:
    return {
        "exam_name": name,
        "grade": 10,
        "subject": "Mathematics",
        "exam_type": "Quarterly",
        "total_marks": 75,
        "duration_minutes": 180,
        "allowed_chapter_numbers": CHAPTERS,
        "allowed_topic_ids": None,
        "difficulty": "default",
        "question_source": source,
        "book_percent": book,
        "new_percent": new,
    }


def _summarize(label: str, result: dict) -> dict:
    exam = result["exam"]
    report = result["report"]
    items = exam.get("questions") or []
    chapters = sorted({q.get("chapter_id") for q in items})
    topics = sorted({tid for q in items for tid in (q.get("topic_ids") or [])})
    book_n = sum(1 for q in items if (q.get("source_type") or "").lower() in ("book", "book_adapted"))
    new_n = sum(1 for q in items if (q.get("source_type") or "").lower() == "new")
    summary = {
        "label": label,
        "exam_id": result["exam_id"],
        "output_dir": result["output_dir"],
        "generated_question_count": len(items),
        "total_marks": sum(int(q.get("marks") or 0) for q in items),
        "source_distribution": {"book_or_adapted": book_n, "new": new_n},
        "chapters_used": chapters,
        "topics_used": topics,
        "out_of_syllabus_count": report["counts"]["out_of_syllabus"],
        "validation": report["overall"],
        "exam_status": report["exam_status"],
        "token_usage": result["usage"],
        "reload_ok": False,
    }
    reloaded = load_exam(result["exam_id"])
    summary["reload_ok"] = reloaded.get("exam_id") == result["exam_id"] and len(reloaded.get("questions") or []) == len(items)
    return summary


def run_one(which: str) -> dict:
    ensure_imports(force_book=False)
    if which == "A":
        cfg = _config("SANITY_A_BOOK", "BOOK", 100, 0)
        eid = "sanity_A_book_ch1-4"
    elif which == "B":
        cfg = _config("SANITY_B_NEW", "NEW", 0, 100)
        eid = "sanity_B_new_ch1-4"
    elif which == "C":
        cfg = _config("SANITY_C_MIXED", "MIXED", 50, 50)
        eid = "sanity_C_mixed_ch1-4"
    else:
        raise ValueError("which must be A, B or C")
    log.info("Starting sanity test %s", which)
    result = run_exam(cfg, exam_id=eid)
    summary = _summarize(which, result)
    out = Path(result["output_dir"]) / "sanity_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Run Grade 10 Math sanity tests A/B/C")
    p.add_argument("--test", choices=["A", "B", "C", "all"], default="all")
    args = p.parse_args()
    tests = ["A", "B", "C"] if args.test == "all" else [args.test]
    summaries = [run_one(t) for t in tests]
    bundle = ROOT / "output" / "exams" / "SANITY_RESULTS.json"
    bundle.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote", bundle)


if __name__ == "__main__":
    main()
