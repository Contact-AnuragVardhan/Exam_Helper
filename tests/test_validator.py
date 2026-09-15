from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.book_importer import import_book
from services.blueprint_builder import build_blueprint
from services.content_gate import build_allowed_content
from services.validator import validate_exam


def _slot_items(bp, allowed, chapter="ch01"):
    qid = allowed.eligible_book_question_ids[0]
    items = []
    for s in bp["slots"]:
        src = "book_adapted" if s["requested_source"] == "book" else "new"
        items.append(
            {
                "question_number": s["question_number"],
                "subquestion_number": s["subquestion_number"],
                "format_id": s["format_id"],
                "marks": s["marks"],
                "source_type": src,
                "chapter_id": s["chapter_id"],
                "topic_ids": [s["chapter_id"] + "_s1"] if False else [],
                "source_pages": [2],
                "source_question_id": qid if src == "book_adapted" else None,
                "question_text_hindi": f"प्रश्न {s['question_number']} हल कीजिए {s['format_id']} {s['subquestion_number']}",
                "answer_key_hindi": "उत्तर",
            }
        )
    return items


def test_validator_pass_and_oos_fail() -> None:
    import_book(force=False)
    allowed = build_allowed_content([1, 2, 3, 4])
    cfg = {
        "exam_name": "Validator unit",
        "exam_type": "Test",
        "total_marks": 75,
        "duration_minutes": 180,
        "allowed_chapter_numbers": [1, 2, 3, 4],
        "difficulty": "default",
        "question_source": "MIXED",
        "book_percent": 50,
        "new_percent": 50,
    }
    bp = build_blueprint(cfg, allowed)
    exam = {
        "header": {
            "exam_title": "Grade 10 Mathematics",
            "grade": 10,
            "subject": "Mathematics",
        },
        "questions": _slot_items(bp, allowed),
    }
    report = validate_exam(exam, bp, allowed)
    assert report["checks"]["CONTENT_GATE"]["result"] == "PASS"
    assert report["checks"]["MARKS"]["result"] == "PASS"
    assert report["checks"]["FORMAT"]["result"] == "PASS"

    bad = copy.deepcopy(exam)
    bad["questions"][0]["chapter_id"] = "ch08"
    bad["questions"][0]["source_pages"] = [120]
    bad["questions"][0]["source_type"] = "new"
    bad["questions"][0]["source_question_id"] = None
    report2 = validate_exam(bad, bp, allowed)
    assert report2["checks"]["CONTENT_GATE"]["result"] == "FAIL"
    assert report2["exam_status"] != "FINAL"
    print("test_validator_pass_and_oos_fail OK")


if __name__ == "__main__":
    test_validator_pass_and_oos_fail()
