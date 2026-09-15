from __future__ import annotations

from dataclasses import asdict
from time import perf_counter

from .blueprint_builder import build_blueprint, print_blueprint, load_profile
from .book_importer import import_book, load_book_index
from .content_gate import build_allowed_content, build_syllabus_display
from .exam_store import save_exam, make_exam_id
from .logger import get_logger
from .question_generator import generate_exam
from .sample_importer import import_mpbse_snapshot, import_sample_exam
from .validator import validate_exam


log = get_logger("pipeline")


def ensure_imports(force_book: bool = False) -> dict:
    book = import_book(force=force_book)
    sample = import_sample_exam()
    mpbse = import_mpbse_snapshot()
    english_book = None
    try:
        from .english_book_importer import import_english_book

        english_book = import_english_book(force=False)
    except Exception as e:
        log.warning("English book import skipped: %s", e)
    return {"book": book, "sample": sample, "mpbse": mpbse, "english_book": english_book}


def imported_content_summary() -> str:
    ensure_imports(force_book=False)
    index = load_book_index()
    book = index["book"]
    profile = load_profile()
    from .paths import load_json, formats_path, sample_data_dir, ROOT

    formats = load_json(formats_path())
    sample_path = sample_data_dir() / "grade10_math_2026_sample.json"
    sample = load_json(sample_path) if sample_path.exists() else {}
    notes = load_json(ROOT / "config" / "source_notes.json")
    lines = []
    lines.append("GRADE 10 — MATHEMATICS")
    lines.append("")
    lines.append("BOOK")
    lines.append(f"  {book.get('title')}")
    lines.append(f"  Language (PDF): {book.get('language')}   declared: {book.get('language_declared_in_config')}")
    lines.append(f"  Chapters: {book['counts']['chapters']}")
    lines.append(f"  Topics: {book['counts']['topics']}")
    lines.append(f"  Book Questions: {book['counts']['book_questions']}")
    lines.append(f"  Examinable questions: {book['counts']['examinable_questions']}")
    lines.append(f"  Status: {book.get('status')}")
    lines.append("")
    lines.append("MPBSE")
    lines.append("  Question Structure: READY")
    wt = profile["chapter_weightage_status"].replace("not_supplied_or_not_verified", "NOT VERIFIED")
    lines.append(f"  Chapter Weightage: {wt.upper() if 'not' in profile['chapter_weightage_status'] else 'VERIFIED'}")
    lines.append("")
    lines.append("FORMAT RULES")
    for f in formats["formats"]:
        lines.append(f"  {f['format_id']} ({f['marks']} mark)")
    lines.append("  Status: READY")
    lines.append("")
    lines.append("SAMPLE EXAMS")
    lines.append(f"  {sample.get('title', '10th Math 2026 Sample Exam')}")
    lines.append(f"  Status: {sample.get('status', 'READY')}")
    lines.append("")
    lines.append("SOURCE FLAGS")
    for fl in notes.get("flags", []):
        lines.append(f"  [{fl['severity']}] {fl['id']}: {fl['text']}")
    try:
        from .english_book_importer import load_english_book_index
        from .english_syllabus import load_active_english_syllabus

        eindex = load_english_book_index()
        ebook = eindex["book"]
        syn = load_active_english_syllabus()
        lines.append("")
        lines.append("GRADE 10 — ENGLISH")
        lines.append(f"  {ebook.get('title')}")
        lines.append(f"  Chapters/poems indexed: {ebook['counts']['chapters']}")
        lines.append(f"  Examinable book questions: {ebook['counts']['examinable_questions']}")
        lines.append("  Q1 syllabus: " + "; ".join(syn.get("all_items") or []))
        if syn.get("missing_books"):
            lines.append("  MISSING BOOK SOURCE: " + ", ".join(syn["missing_books"]))
    except Exception as e:
        lines.append("")
        lines.append(f"GRADE 10 — ENGLISH: not ready ({e})")
    return "\n".join(lines)


def run_exam(exam_config: dict, exam_id: str | None = None) -> dict:
    if str(exam_config.get("subject") or "").lower() == "english":
        return run_english_exam(exam_config, exam_id=exam_id)
    started = perf_counter()
    log.info(
        "Exam generation started subject=Mathematics exam_id=%s chapters=%s",
        exam_id or "auto",
        len(exam_config.get("allowed_chapter_numbers") or []),
    )
    ensure_imports(force_book=False)
    allowed = build_allowed_content(
        exam_config["allowed_chapter_numbers"],
        exam_config.get("allowed_topic_ids"),
        exam_config.get("excluded_question_ids"),
    )
    blueprint = build_blueprint(exam_config, allowed)
    log.info("Blueprint printed\n%s", print_blueprint(blueprint))
    exam, usage = generate_exam(exam_config, blueprint, allowed)
    exam["syllabus"] = build_syllabus_display(allowed, exam_config)
    report = validate_exam(exam, blueprint, allowed)
    exam["validation"] = report
    exam["llm_usage"] = usage
    eid = exam_id or make_exam_id(exam_config.get("exam_name") or "math10")
    out_dir = save_exam(exam, blueprint, report, exam_id=eid)
    log.info(
        "Exam generation completed subject=Mathematics exam_id=%s valid=%s duration_seconds=%.2f",
        eid,
        report.get("valid") if isinstance(report, dict) else None,
        perf_counter() - started,
    )
    return {
        "exam_id": eid,
        "output_dir": str(out_dir),
        "blueprint": blueprint,
        "exam": exam,
        "report": report,
        "usage": usage,
        "allowed": asdict(allowed),
    }


def run_english_exam(exam_config: dict, exam_id: str | None = None, force_book: bool = False) -> dict:
    from .english_book_importer import import_english_book
    from .english_blueprint import build_english_blueprint, print_english_blueprint
    from .english_content_gate import build_english_allowed_content
    from .english_generator import generate_english_exam

    started = perf_counter()
    log.info("Exam generation started subject=English exam_id=%s", exam_id or "auto")
    import_english_book(force=force_book)
    allowed = build_english_allowed_content(exam_config)
    blueprint = build_english_blueprint(exam_config, allowed)
    log.info("English blueprint\n%s", print_english_blueprint(blueprint))
    exam, usage = generate_english_exam(exam_config, blueprint, allowed)
    if not (exam.get("syllabus") or {}).get("groups"):
        exam["syllabus"] = build_syllabus_display(allowed, exam_config)
    eid = exam_id or make_exam_id(exam_config.get("exam_name") or "eng10")
    exam["exam_id"] = eid
    from .english_content_quality import apply_english_content_quality
    from .paths import output_exams_dir

    apply_english_content_quality(exam, output_exams_dir() / eid)
    report = validate_exam(exam, blueprint, allowed)
    exam["validation"] = report
    exam["llm_usage"] = usage
    out_dir = save_exam(exam, blueprint, report, exam_id=eid)
    log.info(
        "Exam generation completed subject=English exam_id=%s valid=%s duration_seconds=%.2f",
        eid,
        report.get("valid") if isinstance(report, dict) else None,
        perf_counter() - started,
    )
    return {
        "exam_id": eid,
        "output_dir": str(out_dir),
        "blueprint": blueprint,
        "exam": exam,
        "report": report,
        "usage": usage,
        "allowed": asdict(allowed),
    }
