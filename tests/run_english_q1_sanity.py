from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.english_book_importer import import_english_book, load_english_book_index
from services.english_syllabus import load_active_english_syllabus
from services.pipeline import run_exam


FORBIDDEN_SNIPPETS = [
    "tiger in the zoo",
    "triumph of surgery",
    "tricki",
    "mrs pumphrey",
    "anne frank",
]


def main() -> None:
    import_english_book(force=False)
    index = load_english_book_index()
    syn = load_active_english_syllabus()
    cfg = {
        "exam_name": "Grade 10 English Quarterly Q1 Sanity",
        "grade": 10,
        "subject": "English",
        "exam_type": "Quarterly",
        "total_marks": 80,
        "duration_minutes": 180,
        "difficulty": "default",
        "question_source": "MIXED",
        "book_percent": 70,
        "new_percent": 30,
    }
    result = run_exam(cfg, exam_id="sanity_english_q1")
    exam = result["exam"]
    report = result["report"]
    items = exam.get("questions") or []
    blob = "\n".join(
        [
            (q.get("question_text") or "")
            + " "
            + (q.get("passage") or "")
            + " "
            + (q.get("choice_b") or "")
            + " "
            + (q.get("chapter_or_poem") or "")
            for q in items
            if (q.get("content_class") or "").upper() == "LITERATURE"
        ]
    ).lower()
    forbidden_hits = [p for p in FORBIDDEN_SNIPPETS if p in blob]
    summary = {
        "exam_id": result["exam_id"],
        "output_dir": result["output_dir"],
        "book_indexed": {
            "title": index["book"].get("title"),
            "chapters": index["book"]["counts"]["chapters"],
            "examinable_questions": index["book"]["counts"]["examinable_questions"],
        },
        "active_syllabus": syn.get("all_items"),
        "blueprint_sections": result["blueprint"].get("sections"),
        "source_counts": {
            "book": sum(1 for q in items if (q.get("source_type") or "").lower() in ("book", "book_adapted")),
            "new": sum(1 for q in items if (q.get("source_type") or "").lower() == "new"),
            "skill": sum(1 for q in items if (q.get("source_type") or "").lower() == "skill"),
        },
        "marks": report["counts"]["marks"],
        "duration_minutes": exam.get("duration_minutes"),
        "out_of_syllabus": report["counts"]["out_of_syllabus"],
        "forbidden_hits": forbidden_hits,
        "missing_sources": report.get("missing_sources") or [],
        "validation": report["overall"],
        "exam_status": report["exam_status"],
        "token_usage": result["usage"],
        "files": ["exam.txt", "exam.pdf", "answer_key.txt", "answer_key.pdf"],
    }
    out = Path(result["output_dir"]) / "sanity_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n" + (Path(result["output_dir"]) / "validation_report.txt").read_text(encoding="utf-8"))
    if forbidden_hits:
        raise SystemExit("Sanity failed: forbidden literature titles present")
    if report["counts"]["out_of_syllabus"] != 0:
        raise SystemExit("Sanity failed: out-of-syllabus literature questions")


if __name__ == "__main__":
    main()
