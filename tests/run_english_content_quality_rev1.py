from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.english_content_quality import word_count
from services.english_syllabus import load_active_english_syllabus
from services.pipeline import run_english_exam


Q3_INSTRUCTION = (
    "Read the following passage carefully and make notes on it using headings "
    "and sub-headings. Also provide a suitable title for your notes."
)
NOTE_RE = re.compile(r"make notes on it using headings|make a suitable note", re.I)
DICT_RE = re.compile(r"\{['\"]label['\"]")


def _block(text: str, start_pat: str, end_pat: str | None = None) -> str:
    m = re.search(start_pat, text, re.I | re.M)
    if not m:
        return ""
    rest = text[m.start() :]
    if end_pat:
        n = re.search(end_pat, rest[4:], re.I | re.M)
        if n:
            rest = rest[: n.start() + 4]
    return rest.strip()


def _q1_passage(exam_txt: str) -> str:
    block = _block(exam_txt, r"^Q1\.", r"^Q2\.")
    lines = []
    for ln in block.splitlines()[1:]:
        if re.match(r"^\s*\(i\)", ln):
            break
        if ln.strip():
            lines.append(ln.strip())
    return " ".join(lines)


def inspect(exam_txt: str, exam: dict, report: dict, out_dir: Path) -> dict:
    defects = []
    q1_pass = _q1_passage(exam_txt)
    q1_wc = word_count(q1_pass)
    if not (120 <= q1_wc <= 160):
        defects.append(f"q1_word_count_{q1_wc}")
    q1_block = _block(exam_txt, r"^Q1\.", r"^Q2\.")
    for lab in ("(i)", "(ii)", "(iii)", "(iv)", "(v)"):
        if lab not in q1_block:
            defects.append(f"q1_missing_{lab}")

    q3 = _block(exam_txt, r"^Q3\.", r"^Q4\.")
    before, after = "", ""
    if "\n" in q3:
        first, rest = q3.split("\n", 1)
        before = first
        after = rest
    if Q3_INSTRUCTION.lower() not in before.lower() and Q3_INSTRUCTION.lower() not in q3.split("\n")[0].lower():
        if Q3_INSTRUCTION.lower() not in q3.lower():
            defects.append("q3_missing_instruction")
    # instruction must appear once, and only before the passage body
    note_hits = NOTE_RE.findall(q3)
    if len(note_hits) != 1:
        defects.append(f"q3_instruction_count_{len(note_hits)}")
    # no second instruction after passage
    lines = q3.splitlines()
    instr_idx = next((i for i, ln in enumerate(lines) if NOTE_RE.search(ln)), -1)
    later = "\n".join(lines[instr_idx + 1 :]) if instr_idx >= 0 else ""
    if NOTE_RE.search(later):
        defects.append("q3_instruction_after_passage")

    q5 = _block(exam_txt, r"^Q5\.", r"^Q6\.")
    if "any one" not in q5.lower():
        defects.append("q5_missing_any_one")
    choices = re.findall(r"^\s*\(([a-d])\)\s+\S", q5, re.I | re.M)
    if [c.lower() for c in choices] != ["a", "b", "c", "d"]:
        defects.append(f"q5_choices_{choices}")
    essay_topics = []
    for q in exam.get("questions") or []:
        if int(q.get("question_number") or 0) == 5:
            essay_topics = q.get("essay_topics") or []
            if int(q.get("marks") or 0) != 5:
                defects.append("q5_marks_changed")
            break
    if len(essay_topics) != 4:
        defects.append(f"q5_topic_count_{len(essay_topics)}")

    q6 = _block(exam_txt, r"^Q6\.", r"^Q7\.")
    if "picture/scene:" in q6.lower():
        defects.append("q6_placeholder_prompt")
    if "observe the picture below" not in q6.lower():
        defects.append("q6_missing_instruction")
    img_name = ""
    img_ok = False
    for q in exam.get("questions") or []:
        if int(q.get("question_number") or 0) == 6:
            img_name = q.get("picture_image") or exam.get("q6_image") or ""
            if (q.get("q6_image_status") or exam.get("q6_status")) == "FAILED" or not img_name:
                defects.append("q6_image_failed")
            break
    pdf_path = out_dir / "exam.pdf"
    if pdf_path.exists():
        import fitz

        doc = fitz.open(pdf_path)
        pdf_text = "".join(page.get_text() for page in doc)
        has_img = any(page.get_images() for page in doc)
        doc.close()
        if not has_img:
            defects.append("q6_image_not_embedded")
        else:
            img_ok = True
        if "picture/scene:" in pdf_text.lower():
            defects.append("q6_prompt_in_pdf")
        if "before you read" in pdf_text.lower():
            defects.append("before_you_read")
        if DICT_RE.search(pdf_text):
            defects.append("raw_dict_or_json")
    else:
        defects.append("missing_exam_pdf")

    q9a = _block(exam_txt, r"^Q9\(a\)\.", r"^Q9\(b\)\.")
    if "dust of snow" not in q9a.lower() and "fire and ice" not in q9a.lower():
        defects.append("q9a_missing_title")
    if q9a.count("\n") < 6:
        defects.append("q9a_not_line_broken")
    if "robert frost" not in q9a.lower() and "—" not in q9a:
        defects.append("q9a_missing_author")
    if "hemlock:" in q9a.lower() or "before you read" in q9a.lower():
        defects.append("q9a_book_furniture")
    q9a_pass = "PASS" if not any(d.startswith("q9a_") for d in defects) else "FAIL"

    q9b = _block(exam_txt, r"^Q9\(b\)\.", r"^Q10\.")
    # passage is lines after heading until (i)
    q9b_lines = []
    for ln in q9b.splitlines()[1:]:
        if re.match(r"^\s*\(i\)", ln):
            break
        if ln.strip():
            q9b_lines.append(ln.strip())
    q9b_extract = " ".join(q9b_lines)
    q9b_wc = word_count(q9b_extract)
    if q9b_wc < 110:
        defects.append(f"q9b_word_count_{q9b_wc}")
    src_chapter = ""
    for q in exam.get("questions") or []:
        if int(q.get("question_number") or 0) == 9 and (q.get("sub_slot") or "") == "b":
            src_chapter = q.get("chapter_or_poem") or ""
            break
    if "before you read" in q9b.lower() or "money order" in q9b.lower():
        defects.append("q9b_book_furniture")

    if report.get("overall") != "PASS":
        defects.append("validation_fail")
    marks = (report.get("counts") or {}).get("marks")
    if marks != 80:
        defects.append(f"marks_{marks}")
    if report.get("counts", {}).get("out_of_syllabus"):
        defects.append("out_of_syllabus")
    if "BEFORE YOU READ" in exam_txt:
        defects.append("before_you_read")
    if DICT_RE.search(exam_txt):
        defects.append("raw_dict_or_json")

    return {
        "pass": not defects,
        "defects": defects,
        "q1_word_count": q1_wc,
        "q5_essay_topics": essay_topics,
        "q6_image": img_name,
        "q6_embedded": img_ok,
        "q9a_rendering": q9a_pass,
        "q9b_word_count": q9b_wc,
        "q9b_chapter": src_chapter,
        "validation": report.get("overall"),
        "marks": marks,
    }


def main() -> None:
    syn = load_active_english_syllabus()
    cfg = {
        "exam_name": "Grade 10 English Quarterly Content Quality Rev1",
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
    result = run_english_exam(cfg, exam_id="english_content_quality_rev1", force_book=False)
    exam = result["exam"]
    report = result["report"]
    out_dir = Path(result["output_dir"])
    exam_txt = (out_dir / "exam.txt").read_text(encoding="utf-8")
    focused = inspect(exam_txt, exam, report, out_dir)
    summary = {
        "exam_id": result["exam_id"],
        "output_folder": str(out_dir),
        "active_syllabus": syn.get("all_items"),
        "marks": report["counts"]["marks"],
        "validation": report["overall"],
        "exam_status": report["exam_status"],
        "q6_status": exam.get("q6_status"),
        "focused_sanity": focused,
        "files": ["exam.txt", "exam.pdf", "answer_key.txt", "answer_key.pdf"],
    }
    (out_dir / "sanity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n" + (out_dir / "validation_report.txt").read_text(encoding="utf-8"))
    print("\nFOCUSED SANITY:", "PASS" if focused["pass"] else "FAIL")
    if focused["defects"]:
        print("DEFECTS:", ", ".join(focused["defects"]))
    print("\n--- Q1 ---\n", _block(exam_txt, r"^Q1\.", r"^Q2\.")[:1200])
    print("\n--- Q3 ---\n", _block(exam_txt, r"^Q3\.", r"^Q4\.")[:900])
    print("\n--- Q5 ---\n", _block(exam_txt, r"^Q5\.", r"^Q6\.")[:700])
    print("\n--- Q6 ---\n", _block(exam_txt, r"^Q6\.", r"^Q7\.")[:700])
    print("\n--- Q9(a) ---\n", _block(exam_txt, r"^Q9\(a\)\.", r"^Q9\(b\)\.")[:1200])
    print("\n--- Q9(b) ---\n", _block(exam_txt, r"^Q9\(b\)\.", r"^Q10\.")[:1400])
    if not focused["pass"]:
        raise SystemExit("Sanity failed: content-quality defects remain")


if __name__ == "__main__":
    main()
