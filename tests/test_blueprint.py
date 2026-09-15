from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.book_importer import import_book
from services.blueprint_builder import build_blueprint
from services.content_gate import build_allowed_content


def _cfg(source="MIXED", book=50, new=50):
    return {
        "exam_name": "Blueprint unit test",
        "exam_type": "Test",
        "total_marks": 75,
        "duration_minutes": 180,
        "allowed_chapter_numbers": [1, 2, 3, 4],
        "difficulty": "default",
        "question_source": source,
        "book_percent": book,
        "new_percent": new,
    }


def test_blueprint_75_and_unverified_weightage() -> None:
    import_book(force=False)
    allowed = build_allowed_content([1, 2, 3, 4])
    bp = build_blueprint(_cfg(), allowed)
    assert bp["total_marks"] == 75
    assert bp["slot_count"] == 48
    assert bp["chapter_weightage_status"] == "not_supplied_or_not_verified"
    assert bp["chapter_weightage_source"] == "unverified"
    assert any("weightage" in w.lower() for w in bp["warnings"])
    used = {s["chapter_id"] for s in bp["slots"]}
    assert used <= set(allowed.allowed_chapter_ids)
    assert "ch05" not in used
    marks = sum(s["marks"] for s in bp["slots"])
    assert marks == 75
    print("test_blueprint_75_and_unverified_weightage OK", bp["format_summary"])


def test_blueprint_book_only() -> None:
    import_book(force=False)
    allowed = build_allowed_content([1, 2, 3, 4])
    bp = build_blueprint(_cfg("BOOK", 100, 0), allowed)
    assert all(s["requested_source"] == "book" for s in bp["slots"])
    print("test_blueprint_book_only OK")


if __name__ == "__main__":
    test_blueprint_75_and_unverified_weightage()
    test_blueprint_book_only()
