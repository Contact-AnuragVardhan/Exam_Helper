from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.book_importer import import_book
from services.content_gate import build_allowed_content
from services.match_columns import build_match_question, judge_match_question
from services.paths import output_exams_dir


def main() -> None:
    import_book(force=False)
    allowed = build_allowed_content([1, 2, 3, 4])
    used: set[str] = set()
    results = []
    out_dir = output_exams_dir() / "match_retest_ch1-4"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["MATCH_COLUMNS RETEST — BOOK only, Chapters 1–4", ""]
    for n in range(1, 6):
        q = build_match_question(allowed, n_pairs=6, used_ids=used, seed=2000 + n)
        judge = judge_match_question(q, allowed)
        rec = {
            "question": n,
            "column_a_en": [p["a_en"] for p in q["pairs"]],
            "column_b_shuffled_hi": q["column_b"],
            "column_a_hi": q["column_a"],
            "answer_mapping": q["answer_mapping"],
            "pairs": q["pairs"],
            "chapters": sorted({p["chapter_id"] for p in q["pairs"]}),
            "topics": sorted({p["topic_id"] for p in q["pairs"]}),
            "pages": sorted({p["source_page"] for p in q["pairs"]}),
            "judge": judge,
        }
        results.append(rec)
        lines.append("=" * 64)
        lines.append(f"QUESTION {n}  [{judge['result']}]")
        lines.append("=" * 64)
        lines.append("Column A")
        for i, p in enumerate(q["pairs"], start=1):
            lines.append(f"  ({i}) {p['a_en']}")
        lines.append("Column B (shuffled)")
        for item in q["column_b"]:
            # show English B in same order as shuffled Hindi B
            label = item.split(")", 1)[0].strip("(")
            pair = next(x for x in q["pairs"] if x["b_label"] == label)
            lines.append(f"  ({label}) {pair['b_en']}")
        lines.append("Answer mapping: " + ", ".join(q["answer_mapping"]))
        lines.append("Sources:")
        for p in q["pairs"]:
            lines.append(
                f"  ({p['a_index']}) {p['chapter_id']} / {p['topic_id']} / "
                f"page {p['source_page']} / {p['source_ref']}"
            )
        lines.append(f"Out of syllabus: {judge['out_of_syllabus_count']}")
        if judge["fails"]:
            lines.append("Fails: " + "; ".join(judge["fails"]))
        lines.append("")
    (out_dir / "match_retest.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = "\n".join(lines)
    (out_dir / "match_retest.txt").write_text(report, encoding="utf-8")
    sys.stdout.buffer.write(report.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")
    print("Saved", out_dir)


if __name__ == "__main__":
    main()
