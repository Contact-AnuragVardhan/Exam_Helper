from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.book_importer import load_book_index, import_book


def test_book_index_counts() -> None:
    import_book(force=False)
    index = load_book_index()
    book = index["book"]
    assert book["counts"]["chapters"] == 14, book["counts"]
    assert book["counts"]["topics"] == 55, book["counts"]
    assert book["counts"]["book_questions"] > 100
    names = [c["chapter_name"] for c in index["chapters"]]
    assert names[0] == "Real Numbers"
    assert names[3] == "Quadratic Equations"
    assert names[-1] == "Probability"
    opt = [e for e in index["exercises"] if e["optional"]]
    assert any(e["exercise_number"] == "5.4" for e in opt)
    ch14 = [c for c in index["chapters"] if c["chapter_number"] <= 4]
    q14 = [q for q in index["questions"] if q["chapter_id"] in {c["chapter_id"] for c in ch14} and q["examinable"]]
    assert len(q14) >= 40, len(q14)
    print("test_book_index_counts OK", book["counts"])


if __name__ == "__main__":
    test_book_index_counts()
