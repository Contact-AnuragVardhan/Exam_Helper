from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.english_book_importer import load_english_book_index
from services.english_syllabus import load_active_english_syllabus
from services.pipeline import run_english_exam


FORBIDDEN_SNIPPETS = [
    "tiger in the zoo",
    "triumph of surgery",
    "tricki",
    "mrs pumphrey",
    "anne frank",
]

DICT_RE = re.compile(r"\{['\"]label['\"]")
ANY_DUP_RE = re.compile(r"\(any\s+\w+\).{0,40}\(any\s+\w+\)", re.I)


def _block(text: str, start_pat: str, end_pat: str | None = None, limit: int = 1400) -> str:
    m = re.search(start_pat, text, re.I | re.M)
    if not m:
        return ""
    rest = text[m.start():]
    if end_pat:
        n = re.search(end_pat, rest[4:], re.I | re.M)
        if n:
            rest = rest[: n.start() + 4]
    return rest[:limit].strip()


def inspect(exam_txt: str, exam: dict, report: dict) -> dict:
    defects = []
    if DICT_RE.search(exam_txt) or "{'label'" in exam_txt or '{"label"' in exam_txt:
        defects.append("raw_dict_or_json_options")
    if "BEFORE YOU READ" in exam_txt:
        defects.append("before_you_read")
    if "TO THE TEACHER" in exam_txt:
        defects.append("to_the_teacher")
    if "Fill out the Money Order form" in exam_txt:
        defects.append("money_order_furniture")
    if "Dust of Sno Dust of Sno" in exam_txt:
        defects.append("repeated_truncated_title")
    if exam_txt.lower().count("fire and ice") >= 8:
        defects.append("repeated_poem_title")
    if ANY_DUP_RE.search(exam_txt):
        defects.append("duplicate_any_n_instruction")
    if not re.search(r"^      A\) ", exam_txt, re.M):
        defects.append("mcq_missing_A_letter_style")
    if not re.search(r"^      B\) ", exam_txt, re.M):
        defects.append("mcq_missing_B_letter_style")
    if report.get("overall") != "PASS":
        defects.append("validation_fail")
    marks = (report.get("counts") or {}).get("marks")
    if marks != 80:
        defects.append(f"marks_{marks}")
    if report.get("counts", {}).get("out_of_syllabus"):
        defects.append("out_of_syllabus")

    samples = {
        "reading_mcq": _block(exam_txt, r"^Q1\.", r"^Q2\."),
        "grammar": _block(exam_txt, r"^Q7\.", r"^Q8\."),
        "extract": _block(exam_txt, r"^Q9\(a\)\.", r"^Q10\."),
        "poem": _block(exam_txt, r"^Q12\.", r"^Q13\."),
        "prose": _block(exam_txt, r"^Q13\.", r"^Q14\."),
    }
    return {
        "pass": not defects,
        "defects": defects,
        "samples": samples,
        "validation": report.get("overall"),
        "marks": marks,
        "exam_status": report.get("exam_status"),
    }


def main() -> None:
    syn = load_active_english_syllabus()
    cfg = {
        "exam_name": "Grade 10 English Quarterly Cleanup Redo",
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
    result = run_english_exam(cfg, exam_id="english_cleanup_redo", force_book=True)
    index = load_english_book_index()
    exam = result["exam"]
    report = result["report"]
    out_dir = Path(result["output_dir"])
    exam_txt = (out_dir / "exam.txt").read_text(encoding="utf-8")
    items = exam.get("questions") or []
    blob = "\n".join(
        [
            (q.get("question_text") or "")
            + " "
            + (q.get("passage") or "")
            + " "
            + (q.get("extract") or "")
            + " "
            + (q.get("choice_b") or "")
            + " "
            + (q.get("chapter_or_poem") or "")
            for q in items
            if (q.get("content_class") or "").upper() == "LITERATURE"
        ]
    ).lower()
    forbidden_hits = [p for p in FORBIDDEN_SNIPPETS if p in blob]
    focused = inspect(exam_txt, exam, report)
    if forbidden_hits:
        focused["defects"].append("forbidden_literature")
        focused["pass"] = False
    summary = {
        "exam_id": result["exam_id"],
        "old_output_folder": str(ROOT / "output" / "exams" / "sanity_english_q1"),
        "new_output_folder": str(out_dir),
        "book_index_rebuilt": True,
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
        "focused_sanity": {
            "pass": focused["pass"],
            "defects": focused["defects"],
            "validation": focused["validation"],
            "marks": focused["marks"],
        },
        "sample_blocks": focused["samples"],
    }
    (out_dir / "sanity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "sample_blocks"}, ensure_ascii=False, indent=2))
    print("\n" + (out_dir / "validation_report.txt").read_text(encoding="utf-8"))
    print("\nFOCUSED SANITY:", "PASS" if focused["pass"] else "FAIL")
    if focused["defects"]:
        print("DEFECTS:", ", ".join(focused["defects"]))
    print("\n--- Reading MCQ ---\n", focused["samples"]["reading_mcq"][:900])
    print("\n--- Poem ---\n", focused["samples"]["poem"][:900])
    print("\n--- Prose ---\n", focused["samples"]["prose"][:900])
    print("\n--- Extract ---\n", focused["samples"]["extract"][:900])
    print("\n--- Grammar ---\n", focused["samples"]["grammar"][:900])
    if forbidden_hits:
        raise SystemExit("Sanity failed: forbidden literature titles present")
    if report["counts"]["out_of_syllabus"] != 0:
        raise SystemExit("Sanity failed: out-of-syllabus literature questions")
    if not focused["pass"]:
        raise SystemExit("Sanity failed: cleanup defects remain")


if __name__ == "__main__":
    main()
