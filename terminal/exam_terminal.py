from __future__ import annotations

import json
import sys
from pathlib import Path

from services.blueprint_builder import build_blueprint, print_blueprint, load_profile, load_formats
from services.book_importer import load_book_index, import_book
from services.content_gate import build_allowed_content
from services.exam_store import load_exam
from services.logger import get_logger
from services.pipeline import ensure_imports, imported_content_summary, run_exam
from services.validator import report_text, validate_exam


log = get_logger("terminal")


def _pause() -> None:
    input("\nPress Enter to continue...")


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    if not val and default is not None:
        return default
    return val


def _print(title: str, body: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)
    print(body)


def view_imported() -> None:
    _print("VIEW IMPORTED CONTENT", imported_content_summary())
    print("\nDrill-down:  b=book details  s=source flags  Enter=back")
    choice = input("> ").strip().lower()
    if choice == "b":
        view_chapters()
    elif choice == "s":
        from services.paths import ROOT, load_json
        notes = load_json(ROOT / "config" / "source_notes.json")
        print(json.dumps(notes, indent=2, ensure_ascii=False))


def view_chapters() -> None:
    index = load_book_index()
    lines = ["CHAPTERS / TOPICS", ""]
    topics = {t["topic_id"]: t for t in index["topics"]}
    for c in index["chapters"]:
        lines.append(
            f"Ch {c['chapter_number']:2d}  {c['chapter_name']}  "
            f"pages {c['start_page']}-{c['end_page']}  exercises={len(c['exercises'])}"
        )
        for tid in c.get("topics") or []:
            t = topics.get(tid)
            if t:
                lines.append(f"     {t['section_number']} {t['topic_name']}  p{t['start_page']}-{t['end_page']}")
    _print("BOOK CHAPTERS / TOPICS", "\n".join(lines))


def view_questions() -> None:
    index = load_book_index()
    raw = _ask("Chapter number to list (blank=1-4)", "1-4")
    if "-" in raw:
        a, b = raw.split("-", 1)
        wanted = {f"ch{int(x):02d}" for x in range(int(a), int(b) + 1)}
    else:
        wanted = {f"ch{int(raw):02d}"}
    qs = [q for q in index["questions"] if q["chapter_id"] in wanted]
    lines = [f"{len(qs)} questions (showing first 40)", ""]
    for q in qs[:40]:
        flag = "Y" if q.get("examinable") else "N"
        lines.append(
            f"{q['question_id']}  exam={flag}  p{q['source_page']}  {q['question_text'][:110]}"
        )
    _print("BOOK QUESTIONS", "\n".join(lines))


def view_profile() -> None:
    subj = (_SESSION.get("exam_config") or {}).get("subject") or _SESSION.get("subject")
    profile = load_profile(subj if str(subj).lower() == "english" else None)
    _print("EXAM PROFILE", json.dumps(profile, indent=2, ensure_ascii=False))


def view_formats() -> None:
    subj = (_SESSION.get("exam_config") or {}).get("subject") or _SESSION.get("subject")
    formats = load_formats(subj if str(subj).lower() == "english" else None)
    lines = []
    for f in formats["formats"]:
        lines.append(f"{f['format_id']}  marks={f['marks']}  {f['format_name']}")
        lines.append(f"    task: {f['student_task']}")
        lines.append("")
    _print("FORMAT RULES", "\n".join(lines))


_SESSION: dict = {
    "exam_config": None,
    "last_result": None,
    "subject": "Mathematics",
}


def default_config() -> dict:
    return {
        "exam_name": "Grade 10 Mathematics Quarterly Pilot",
        "grade": 10,
        "subject": "Mathematics",
        "exam_type": "Quarterly",
        "total_marks": 75,
        "duration_minutes": 180,
        "allowed_chapter_numbers": [1, 2, 3, 4],
        "allowed_topic_ids": None,
        "excluded_question_ids": [],
        "difficulty": "default",
        "question_source": "BOOK",
        "book_percent": 100,
        "new_percent": 0,
    }


def default_english_config() -> dict:
    return {
        "exam_name": "Grade 10 English Quarterly",
        "grade": 10,
        "subject": "English",
        "exam_type": "Quarterly",
        "total_marks": 80,
        "duration_minutes": 180,
        "book": "First Flight",
        "syllabus": "Q1 / Quarterly",
        "difficulty": "default",
        "question_source": "MIXED",
        "book_percent": 70,
        "new_percent": 30,
    }


def configure_exam() -> None:
    subj = _ask("Subject (Mathematics / English)", _SESSION.get("subject") or "Mathematics")
    _SESSION["subject"] = "English" if subj.lower().startswith("eng") else "Mathematics"
    if _SESSION["subject"] == "English":
        cfg = default_english_config()
        print("\nCONFIGURE TEST EXAM  (Grade 10 English)")
        print("GRADE: 10")
        print("SUBJECT: English")
        print("BOOK: First Flight")
        print("SYLLABUS: Q1 / Quarterly")
        cfg["exam_name"] = _ask("Exam name", cfg["exam_name"])
        cfg["exam_type"] = _ask("Exam type (Quarterly / Test / Custom)", cfg["exam_type"])
        src = _ask("Question source (BOOK / NEW / MIXED)", "MIXED").upper()
        cfg["question_source"] = src
        if src == "MIXED":
            cfg["book_percent"] = 70
            cfg["new_percent"] = 30
        elif src == "BOOK":
            cfg["book_percent"], cfg["new_percent"] = 100, 0
        else:
            cfg["book_percent"], cfg["new_percent"] = 0, 100
        _SESSION["exam_config"] = cfg
        print("\nSaved configuration:")
        print(json.dumps(cfg, indent=2))
        return
    cfg = default_config()
    print("\nCONFIGURE TEST EXAM  (Grade 10 Mathematics is fixed)")
    cfg["exam_name"] = _ask("Exam name", cfg["exam_name"])
    cfg["exam_type"] = _ask("Exam type (Quarterly / Test / Custom)", cfg["exam_type"])
    cfg["total_marks"] = int(_ask("Total marks", str(cfg["total_marks"])))
    cfg["duration_minutes"] = int(_ask("Duration minutes", str(cfg["duration_minutes"])))
    ch = _ask("Allowed chapters (comma, e.g. 1,2,3,4)", "1,2,3,4")
    cfg["allowed_chapter_numbers"] = [int(x.strip()) for x in ch.split(",") if x.strip()]
    topics = _ask("Allowed topic ids (blank=all topics in those chapters)", "")
    cfg["allowed_topic_ids"] = [t.strip() for t in topics.split(",") if t.strip()] or None
    cfg["difficulty"] = _ask("Difficulty (Easy / Default / Hard)", "Default").lower()
    src = _ask("Question source (BOOK / NEW / MIXED)", "BOOK").upper()
    cfg["question_source"] = src
    if src == "MIXED":
        bp = int(_ask("Book percent", "50"))
        cfg["book_percent"] = bp
        cfg["new_percent"] = 100 - bp
    elif src == "BOOK":
        cfg["book_percent"], cfg["new_percent"] = 100, 0
    else:
        cfg["book_percent"], cfg["new_percent"] = 0, 100
    _SESSION["exam_config"] = cfg
    print("\nSaved configuration:")
    print(json.dumps(cfg, indent=2))


def _require_config() -> dict:
    if not _SESSION["exam_config"]:
        if _SESSION.get("subject") == "English":
            print("No configuration yet — loading default Grade 10 English Q1 MIXED.")
            _SESSION["exam_config"] = default_english_config()
        else:
            print("No configuration yet — loading default Chapters 1-4 BOOK.")
            _SESSION["exam_config"] = default_config()
    return _SESSION["exam_config"]


def build_bp() -> None:
    cfg = _require_config()
    if str(cfg.get("subject") or "").lower() == "english":
        from services.english_blueprint import build_english_blueprint, print_english_blueprint
        from services.english_content_gate import build_english_allowed_content

        allowed = build_english_allowed_content(cfg)
        bp = build_english_blueprint(cfg, allowed)
        _SESSION["blueprint"] = bp
        _SESSION["allowed"] = allowed
        _print("EXAM BLUEPRINT", print_english_blueprint(bp))
        return
    allowed = build_allowed_content(cfg["allowed_chapter_numbers"], cfg.get("allowed_topic_ids"))
    bp = build_blueprint(cfg, allowed)
    _SESSION["blueprint"] = bp
    _SESSION["allowed"] = allowed
    _print("EXAM BLUEPRINT", print_blueprint(bp))


def generate() -> None:
    cfg = _require_config()
    if str(cfg.get("subject") or "").lower() == "english":
        from services.english_blueprint import build_english_blueprint, print_english_blueprint
        from services.english_content_gate import build_english_allowed_content

        allowed = build_english_allowed_content(cfg)
        bp = build_english_blueprint(cfg, allowed)
        print(print_english_blueprint(bp))
    print("\nGenerating exam (this may take a few minutes)...")
    result = run_exam(cfg)
    _SESSION["last_result"] = result
    r = result["report"]
    print(f"\nSaved: {result['output_dir']}")
    print(f"Validation: {r['overall']}  status={r['exam_status']}")
    print(f"Questions: {r['counts']['questions']}  marks={r['counts']['marks']}  OOS={r['counts']['out_of_syllabus']}")
    print(f"LLM usage: {result['usage']}")
    print(report_text(r))


def validate_last() -> None:
    last = _SESSION.get("last_result")
    if not last:
        print("No exam in this session. Generate first, or load from output/exams.")
        eid = _ask("Exam id to load (blank=cancel)", "")
        if not eid:
            return
        exam = load_exam(eid)
        print(json.dumps(exam.get("validation"), indent=2, ensure_ascii=False)[:4000])
        return
    print(report_text(last["report"]))


def save_last() -> None:
    last = _SESSION.get("last_result")
    if not last:
        print("Nothing to save. Generate an exam first (option 8 already saves).")
        return
    print(f"Already saved at: {last['output_dir']}")
    print("Files: exam.json, exam.txt, exam.pdf, answer_key.txt, answer_key.pdf, validation_report.txt, blueprint.json")


def menu() -> None:
    log.info("Developer terminal startup")
    ensure_imports(force_book=False)
    while True:
        print("\n" + "=" * 64)
        print("EXAM REV 2 — DEVELOPER TERMINAL")
        print("=" * 64)
        print("1. View Imported Content")
        print("2. View Book Chapters / Topics")
        print("3. View Book Questions")
        print("4. View Exam Profile")
        print("5. View FORMAT Rules")
        print("6. Configure Test Exam")
        print("7. Build Exam Blueprint")
        print("8. Generate Exam")
        print("9. Validate Exam")
        print("10. Save Exam + Answer Key")
        print("0. Exit")
        choice = input("\nSelect: ").strip()
        try:
            if choice == "1":
                view_imported()
            elif choice == "2":
                view_chapters()
            elif choice == "3":
                view_questions()
            elif choice == "4":
                view_profile()
            elif choice == "5":
                view_formats()
            elif choice == "6":
                configure_exam()
            elif choice == "7":
                build_bp()
            elif choice == "8":
                generate()
            elif choice == "9":
                validate_last()
            elif choice == "10":
                save_last()
            elif choice == "0":
                print("Exit.")
                return
            else:
                print("Unknown option.")
        except Exception as e:
            log.exception("Terminal action failed")
            print(f"\nERROR: {e}")
        _pause()


def main() -> None:
    menu()


if __name__ == "__main__":
    main()
