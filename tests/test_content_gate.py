from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.book_importer import import_book
from services.content_gate import build_allowed_content, assert_question_allowed


def test_gate_allows_only_selected_chapters() -> None:
    import_book(force=False)
    allowed = build_allowed_content([1, 2, 3, 4])
    assert allowed.allowed_chapter_ids == ["ch01", "ch02", "ch03", "ch04"]
    assert allowed.eligible_book_question_ids
    assert all(qid.startswith("bq_ch0") for qid in allowed.eligible_book_question_ids)
    assert not any("ch05" in qid for qid in allowed.eligible_book_question_ids)

    good = {
        "chapter_id": "ch01",
        "topic_ids": ["ch01_s2"],
        "source_pages": [5],
        "source_type": "book_adapted",
        "source_question_id": allowed.eligible_book_question_ids[0],
    }
    assert assert_question_allowed(good, allowed) == []

    bad = {
        "chapter_id": "ch05",
        "topic_ids": ["ch05_s1"],
        "source_pages": [55],
        "source_type": "new",
        "source_question_id": None,
    }
    fails = assert_question_allowed(bad, allowed)
    assert fails, "Chapter 5 must be rejected for a Ch 1-4 gate."
    print("test_gate_allows_only_selected_chapters OK", len(allowed.eligible_book_question_ids))


def test_topic_filter_stays_inside_chapter() -> None:
    import_book(force=False)
    allowed = build_allowed_content([1], allowed_topic_ids=["ch01_s3"])
    assert allowed.allowed_topic_ids == ["ch01_s3"]
    try:
        build_allowed_content([1], allowed_topic_ids=["ch05_s1"])
        raise AssertionError("out-of-chapter topic should raise")
    except ValueError:
        pass
    print("test_topic_filter_stays_inside_chapter OK")


if __name__ == "__main__":
    test_gate_allows_only_selected_chapters()
    test_topic_filter_stays_inside_chapter()
