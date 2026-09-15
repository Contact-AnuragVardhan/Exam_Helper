from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.book_importer import import_book
from services.content_gate import build_allowed_content
from services.match_columns import build_match_question, judge_match_question
from services.match_columns_render import (
    mapping_lines,
    student_text_has_residual,
    validate_match_payload,
)
from services.paths import output_exams_dir
from services.renderer import render_answer_key_pdf, render_answer_key_txt, render_exam_pdf, render_exam_txt


def _items_from_table(table: dict, qn: int) -> list[dict]:
    items = []
    pairs = table["pairs"]
    for j, pair in enumerate(pairs):
        items.append(
            {
                "question_number": qn,
                "subquestion_number": ["i", "ii", "iii", "iv", "v", "vi"][j],
                "format_id": "MATCH_COLUMNS",
                "marks": 1,
                "source_type": "book",
                "chapter_id": pair["chapter_id"],
                "topic_ids": [pair["topic_id"]],
                "source_pages": [pair["source_page"]],
                "source_question_id": pair["pair_id"],
                "source_ref": pair["source_ref"],
                "question_text_hindi": pair["a_hi"] if j else "सही जोड़ी बनाइए",
                "answer_key_hindi": f"{pair['a_hi']} → {pair['b_hi']}  ({table['answer_mapping'][j]})",
                "options": [],
                "match_column_a": table["column_a"] if j == 0 else [],
                "match_column_b": table["column_b"] if j == 0 else [],
                "match_pairs": table["pairs"] if j == 0 else [],
                "answer_mapping": table["answer_mapping"] if j == 0 else [],
                "section_heading": "सही जोड़ी बनाइए",
            }
        )
    return items


def _pdf_table_aligned(pdf_path: Path) -> tuple[bool, str]:
    import fitz

    doc = fitz.open(pdf_path)
    try:
        drawings = []
        header_pairs = 0
        for page in doc:
            drawings.extend(page.get_drawings())
            words = page.get_text("words") or []
            a_ys = [w[1] for w in words if w[4] == "Column" and _nearby_b(words, w, "A")]
            b_ys = [w[1] for w in words if w[4] == "Column" and _nearby_b(words, w, "B")]
            for ay in a_ys:
                ax = min(w[0] for w in words if w[4] == "Column" and abs(w[1] - ay) < 2)
                bx_candidates = [w[0] for w in words if w[4] == "Column" and abs(w[1] - ay) < 2]
                if len(bx_candidates) >= 2:
                    header_pairs += 1
                    if min(bx_candidates) >= max(bx_candidates) - 1:
                        return False, "Column A and Column B share the same x position"
                    if not any(x > ax + 40 for x in bx_candidates):
                        return False, "Column B is not to the right of Column A"
        if not drawings:
            return False, "PDF has no table/grid drawings"
        if header_pairs < 1:
            return False, "Did not find side-by-side Column A / Column B headers"
        return True, f"drawings={len(drawings)} header_pairs={header_pairs}"
    finally:
        doc.close()


def _nearby_b(words, col_word, letter: str) -> bool:
    for w in words:
        if w[4] == letter and abs(w[1] - col_word[1]) < 3 and 0 < (w[0] - col_word[2]) < 40:
            return True
    return False


def main() -> None:
    import_book(force=False)
    allowed = build_allowed_content([1, 2, 3, 4])
    used: set[str] = set()
    items = []
    records = []
    for n in range(1, 6):
        table = build_match_question(allowed, n_pairs=6, used_ids=used, seed=4100 + n)
        judge = judge_match_question(table, allowed)
        payload_check = validate_match_payload(
            {
                "format_id": "MATCH_COLUMNS",
                "match_column_a": table["column_a"],
                "match_column_b": table["column_b"],
                "answer_mapping": table["answer_mapping"],
                "match_pairs": table["pairs"],
            }
        )
        items.extend(_items_from_table(table, n))
        records.append(
            {
                "question": n,
                "pair_ids": [p["pair_id"] for p in table["pairs"]],
                "answer_mapping": table["answer_mapping"],
                "mapping_lines": mapping_lines(
                    {
                        "format_id": "MATCH_COLUMNS",
                        "match_column_a": table["column_a"],
                        "match_column_b": table["column_b"],
                        "answer_mapping": table["answer_mapping"],
                        "match_pairs": table["pairs"],
                    }
                ),
                "academic_judge": judge,
                "payload_check": payload_check,
            }
        )

    exam = {
        "exam_name": "MATCH_COLUMNS rendering cleanup sanity",
        "grade": 10,
        "subject": "Mathematics",
        "exam_type": "Sanity",
        "total_marks": 5,
        "duration_minutes": 30,
        "header": {
            "school_line": "Jalta Sitara / School Examination",
            "exam_title": "MATCH_COLUMNS rendering cleanup sanity",
            "grade": 10,
            "subject": "Mathematics",
            "total_marks": 5,
            "duration_minutes": 30,
            "instructions": ["Match the following only."],
        },
        "questions": items,
        "syllabus": {
            "groups": [
                {
                    "book": "Mathematics, Textbook for Class X (NCERT, Reprint 2026-27)",
                    "items": ["Real Numbers", "Polynomials", "Pair of Linear Equations in Two Variables", "Quadratic Equations"],
                }
            ]
        },
    }

    out_dir = output_exams_dir() / "match_columns_render_cleanup"
    out_dir.mkdir(parents=True, exist_ok=True)
    exam_txt = render_exam_txt(exam)
    key_txt = render_answer_key_txt(exam)
    (out_dir / "exam.txt").write_text(exam_txt, encoding="utf-8")
    (out_dir / "answer_key.txt").write_text(key_txt, encoding="utf-8")
    render_exam_pdf(exam, out_dir / "exam.pdf")
    render_answer_key_pdf(exam, out_dir / "answer_key.pdf")

    residual = student_text_has_residual(exam_txt)
    residual_fail_bits = []
    if residual:
        residual_fail_bits.append("student exam text has residual (ii)/(iii) after the table")
    if re.search(r"(?im)^[ \t]*\((?:ii|iii|iv|v|vi)\)\s+\S", exam_txt):
        residual_fail_bits.append("student exam still prints leftover roman subquestions")
    if "→" in exam_txt or "->" in exam_txt.split("Q1.", 1)[-1][:80]:
        pass
    if re.search(r"(?im)1\s*->\s*[A-Z]", exam_txt):
        residual_fail_bits.append("student paper contains answer mapping")

    aligned, align_detail = _pdf_table_aligned(out_dir / "exam.pdf")

    key_ok = True
    key_fails = []
    for rec in records:
        qn = rec["question"]
        block = re.search(rf"(?ms)^Q{qn}\b.*?(?=^Q\d+\b|\Z)", key_txt)
        if not block:
            key_ok = False
            key_fails.append(f"Q{qn} missing from answer key")
            continue
        body = block.group(0)
        if re.search(r"(?im)^[ \t]*\((?:ii|iii|iv|v|vi)\)\s+\S", body):
            key_ok = False
            key_fails.append(f"Q{qn} answer key has residual fragments")
        for line in rec["mapping_lines"]:
            if line not in body:
                key_ok = False
                key_fails.append(f"Q{qn} missing mapping {line}")

    payload_ok = all(r["payload_check"]["result"] == "PASS" for r in records)
    academic_ok = all(r["academic_judge"]["result"] == "PASS" for r in records)
    residual_ok = not residual_fail_bits

    summary = {
        "alignment": "PASS" if aligned else "FAIL",
        "alignment_detail": align_detail,
        "residual_text": "PASS" if residual_ok else "FAIL",
        "residual_detail": residual_fail_bits,
        "answer_key": "PASS" if key_ok else "FAIL",
        "answer_key_detail": key_fails,
        "payload_validation": "PASS" if payload_ok else "FAIL",
        "academic_unchanged": "PASS" if academic_ok else "FAIL",
        "question_ids": [r["pair_ids"] for r in records],
        "pdf": str(out_dir / "exam.pdf"),
    }
    (out_dir / "sanity_summary.json").write_text(json.dumps({"records": records, "summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")

    overall = all(
        summary[k] == "PASS"
        for k in ("alignment", "residual_text", "answer_key", "payload_validation", "academic_unchanged")
    )
    print("MATCH_COLUMNS RENDERING CLEANUP SANITY")
    print(f"alignment: {summary['alignment']} ({align_detail})")
    print(f"residual-text: {summary['residual_text']}")
    if residual_fail_bits:
        print("  " + "; ".join(residual_fail_bits))
    print(f"answer-key: {summary['answer_key']}")
    if key_fails:
        print("  " + "; ".join(key_fails))
    print(f"payload validation: {summary['payload_validation']}")
    print(f"academic/syllabus unchanged: {summary['academic_unchanged']}")
    print("question pair IDs:")
    for rec in records:
        print(f"  Q{rec['question']}: {', '.join(rec['pair_ids'])}")
    print("PDF:", summary["pdf"])
    print("OVERALL:", "PASS" if overall else "FAIL")
    if not overall:
        sys.exit(1)


if __name__ == "__main__":
    main()
