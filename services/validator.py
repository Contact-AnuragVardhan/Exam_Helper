from __future__ import annotations

import hashlib
import re
import unicodedata

from .content_gate import assert_question_allowed
from .logger import get_logger
from .models import AllowedContentSet
from .paths import load_json, exam_profile_path
from .book_importer import load_book_index
from .match_columns import is_filler_text


log = get_logger("validator")

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
LATIN_RE = re.compile(r"[A-Za-z]")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\u0900-\u097F]+", "", t)
    return t


def validate_exam(exam: dict, blueprint: dict, allowed: AllowedContentSet) -> dict:
    subject = (exam.get("subject") or blueprint.get("subject") or "Mathematics")
    profile = load_json(exam_profile_path(subject if str(subject).lower() == "english" else None))
    items = exam.get("questions") or []
    checks = {}

    checks["CONTENT_GATE"] = _check_content_gate(items, allowed)
    checks["MARKS"] = _check_marks(items, blueprint, subject)
    checks["FORMAT"] = _check_format(items, blueprint)
    checks["QUESTION_SOURCE"] = _check_source(items, blueprint, profile, subject)
    checks["BOOK_TRACEABILITY"] = _check_book_trace(items, allowed, subject)
    checks["NEW_QUESTION_TRACEABILITY"] = _check_new_trace(items, allowed, subject)
    checks["LANGUAGE"] = _check_language(exam, items)
    checks["DUPLICATES"] = _check_duplicates(items)
    checks["ANSWER_KEY"] = _check_answers(items)
    checks["MATCH_QUALITY"] = _check_match_quality(items, allowed)
    if str(subject).lower() == "english":
        checks["LITERATURE_SYLLABUS"] = _check_english_forbidden(items, allowed)

    hard = [k for k, v in checks.items() if v["result"] == "FAIL"]
    overall = "FAIL" if hard else "PASS"
    exam_status = "FINAL" if overall == "PASS" else "DRAFT_FAIL"
    report = {
        "overall": overall,
        "exam_status": exam_status,
        "subject": subject,
        "checks": checks,
        "counts": {
            "questions": len(items),
            "marks": sum(_item_marks(q) for q in items),
            "out_of_syllabus": checks["CONTENT_GATE"].get("out_of_syllabus_count", 0),
            "book": sum(1 for q in items if (q.get("source_type") or "").lower() in ("book", "book_adapted")),
            "new": sum(1 for q in items if (q.get("source_type") or "").lower() == "new"),
            "skill": sum(1 for q in items if (q.get("source_type") or "").lower() == "skill"),
        },
        "missing_sources": list(getattr(allowed, "missing_sources", None) or exam.get("missing_sources") or []),
    }
    log.info("Validation %s status=%s fails=%s", overall, exam_status, hard)
    return report


def _fail(msg: str, **extra) -> dict:
    d = {"result": "FAIL", "detail": msg}
    d.update(extra)
    return d


def _pass(msg: str, **extra) -> dict:
    d = {"result": "PASS", "detail": msg}
    d.update(extra)
    return d


def _check_content_gate(items: list[dict], allowed: AllowedContentSet) -> dict:
    bad = []
    for q in items:
        reasons = assert_question_allowed(q, allowed)
        if reasons:
            bad.append({"question_number": q.get("question_number"), "subquestion_number": q.get("subquestion_number"), "reasons": reasons})
    if bad:
        return _fail(
            f"{len(bad)} question(s) outside allowed content.",
            out_of_syllabus_count=len(bad),
            items=bad,
        )
    return _pass("Zero questions outside allowed chapters/topics.", out_of_syllabus_count=0)


def _item_marks(q: dict) -> int:
    if q.get("counted_marks") is not None and str(q.get("counted_marks")).strip() != "":
        try:
            return int(q.get("counted_marks") or 0)
        except (TypeError, ValueError):
            pass
    return int(q.get("marks") or 0)


def _qtext(q: dict) -> str:
    return (q.get("question_text") or q.get("question_text_hindi") or "").strip()


def _answer(q: dict) -> str:
    return (q.get("answer_key") or q.get("answer_key_hindi") or "").strip()


def _check_marks(items: list[dict], blueprint: dict, subject: str = "Mathematics") -> dict:
    got = sum(_item_marks(q) for q in items)
    want = int(blueprint["total_marks"])
    if got != want:
        return _fail(f"Total marks {got} != configured {want}.")
    return _pass(f"Total marks {got} match configured total.")


def _check_format(items: list[dict], blueprint: dict) -> dict:
    want = {}
    for s in blueprint["slots"]:
        key = (s["question_number"], s["subquestion_number"], s["format_id"], s["marks"])
        want[key] = want.get(key, 0) + 1
    got = {}
    for q in items:
        key = (q.get("question_number"), q.get("subquestion_number"), q.get("format_id"), int(q.get("marks") or 0))
        got[key] = got.get(key, 0) + 1
    if want != got:
        missing = [k for k in want if want[k] != got.get(k)]
        extra = [k for k in got if k not in want]
        return _fail("Format/count/marks do not match blueprint.", missing=missing[:12], extra=extra[:12])
    return _pass("Format counts and marks match the blueprint.")


def _check_source(items: list[dict], blueprint: dict, profile: dict, subject: str = "Mathematics") -> dict:
    def bucket(src: str) -> str:
        s = (src or "").lower()
        if s == "skill":
            return "skill"
        if s in ("book", "book_adapted"):
            return "book"
        return "new"

    got_book = sum(1 for q in items if bucket(q.get("source_type")) == "book")
    got_new = sum(1 for q in items if bucket(q.get("source_type")) == "new")
    got_skill = sum(1 for q in items if bucket(q.get("source_type")) == "skill")
    want_book = sum(1 for s in blueprint["slots"] if s["requested_source"] == "book")
    want_new = sum(1 for s in blueprint["slots"] if s["requested_source"] == "new")
    tol = int(profile["validation_rules"].get("mixed_distribution_tolerance_percent", 10))
    n = max(1, len(items))
    actual_book_pct = 100.0 * got_book / n
    requested = blueprint["question_source"]
    ok = True
    if str(subject).lower() == "english":
        lit = [q for q in items if (q.get("content_class") or "").upper() == "LITERATURE"]
        if requested == "BOOK" and any((q.get("source_type") or "").lower() == "new" for q in lit):
            ok = False
        if requested == "NEW" and any((q.get("source_type") or "").lower() in ("book", "book_adapted") for q in lit):
            ok = False
        extra = {
            "actual_distribution": {"book": got_book, "new": got_new, "skill": got_skill},
            "requested_distribution": {"book": want_book, "new": want_new, "book_percent": blueprint["book_percent"]},
        }
        detail = (
            f"requested={requested} book={got_book} new={got_new} skill={got_skill}"
        )
        if not ok:
            return _fail("Question source distribution not reasonably satisfied. " + detail, **extra)
        return _pass(detail, **extra)
    if requested == "BOOK" and got_new:
        ok = False
    if requested == "NEW" and got_book:
        ok = False
    if requested == "MIXED":
        if got_book == 0 or got_new == 0:
            ok = False
        if abs(actual_book_pct - blueprint["book_percent"]) > tol:
            ok = False
    detail = (
        f"requested={requested} book_items={got_book}/{want_book} new_items={got_new}/{want_new} "
        f"actual_book_pct={actual_book_pct:.1f}"
    )
    extra = {
        "actual_distribution": {"book": got_book, "new": got_new, "book_percent": round(actual_book_pct, 1)},
        "requested_distribution": {"book": want_book, "new": want_new, "book_percent": blueprint["book_percent"]},
    }
    if not ok:
        return _fail("Question source distribution not reasonably satisfied. " + detail, **extra)
    return _pass(detail, **extra)


def _check_book_trace(items: list[dict], allowed: AllowedContentSet, subject: str = "Mathematics") -> dict:
    if str(subject).lower() == "english":
        from .english_book_importer import load_english_book_index

        index = load_english_book_index()
    else:
        index = load_book_index()
    qmap = {q["question_id"]: q for q in index["questions"]}
    bad = []
    for q in items:
        src = (q.get("source_type") or "").lower()
        if src not in ("book", "book_adapted"):
            continue
        if q.get("format_id") == "MATCH_COLUMNS" and q.get("source_ref"):
            if q.get("chapter_id") not in allowed.allowed_chapter_ids:
                bad.append({"q": q.get("question_number"), "reason": "match chapter not allowed"})
            elif not q.get("source_pages"):
                bad.append({"q": q.get("question_number"), "reason": "match missing source page"})
            continue
        sqid = q.get("source_question_id")
        if not sqid or sqid not in qmap:
            bad.append({"q": q.get("question_number"), "reason": "missing/unknown source_question_id"})
            continue
        bq = qmap[sqid]
        if sqid not in allowed.eligible_book_question_ids:
            bad.append({"q": q.get("question_number"), "reason": "source not eligible"})
        if not bq.get("source_page"):
            bad.append({"q": q.get("question_number"), "reason": "book question has no source_page"})
    if bad:
        return _fail(f"{len(bad)} book item(s) failed traceability.", items=bad)
    n = sum(1 for q in items if (q.get("source_type") or "").lower() in ("book", "book_adapted"))
    return _pass(f"{n} book/book_adapted item(s) trace to indexed textbook questions.")


def _check_new_trace(items: list[dict], allowed: AllowedContentSet, subject: str = "Mathematics") -> dict:
    bad = []
    for q in items:
        src = (q.get("source_type") or "").lower()
        if src != "new":
            continue
        if str(subject).lower() == "english" and (q.get("content_class") or "").upper() != "LITERATURE":
            continue
        if q.get("chapter_id") not in allowed.allowed_chapter_ids:
            bad.append({"q": q.get("question_number"), "reason": "chapter not allowed"})
        pages = q.get("source_pages") or []
        if not pages:
            bad.append({"q": q.get("question_number"), "reason": "new question missing source_pages"})
    if bad:
        return _fail(f"{len(bad)} new item(s) failed allowed-concept traceability.", items=bad)
    n = sum(1 for q in items if (q.get("source_type") or "").lower() == "new")
    return _pass(f"{n} new item(s) point at allowed chapter pages.")


def _check_language(exam: dict, items: list[dict]) -> dict:
    header = exam.get("header") or {}
    header_text = " ".join(str(v) for v in header.values())
    if DEVANAGARI_RE.search(header_text):
        return _fail("Exam header contains Devanagari; specification requires English header.")
    if str(exam.get("subject") or "").lower() == "english":
        missing = []
        for q in items:
            body = _qtext(q)
            if not LATIN_RE.search(body):
                missing.append(q.get("question_number"))
        if missing:
            return _fail(f"{len(missing)} English question body/bodies lack Latin script.", items=missing[:12])
        return _pass("Header is English; question bodies are English.")
    missing_hi = []
    for q in items:
        body = q.get("question_text_hindi") or ""
        if not DEVANAGARI_RE.search(body):
            missing_hi.append(q.get("question_number"))
    if missing_hi:
        return _fail(f"{len(missing_hi)} question body/bodies lack Devanagari script.", items=missing_hi[:12])
    return _pass("Header is English; question bodies contain Hindi (Devanagari).")


def _check_duplicates(items: list[dict]) -> dict:
    seen = {}
    dups = []
    for q in items:
        key = _norm(_qtext(q))
        if len(key) < 12:
            continue
        if key in seen:
            dups.append((seen[key], q.get("question_number")))
        else:
            seen[key] = q.get("question_number")
    if dups:
        return _fail(f"{len(dups)} duplicate/near-duplicate question text(s).", items=dups)
    return _pass("No duplicate question bodies detected.")


def _check_answers(items: list[dict]) -> dict:
    missing = []
    for q in items:
        ans = _answer(q)
        if not ans:
            missing.append(q.get("question_number"))
    if missing:
        return _fail(f"{len(missing)} item(s) missing answer key.", items=missing[:12])
    return _pass("Every item has an answer key.")


def _check_match_quality(items: list[dict], allowed: AllowedContentSet) -> dict:
    match_items = [q for q in items if q.get("format_id") == "MATCH_COLUMNS"]
    if not match_items:
        return _pass("No MATCH_COLUMNS items.")
    bad = []
    for q in match_items:
        texts = list(q.get("match_column_a") or []) + list(q.get("match_column_b") or [])
        for t in texts:
            body = re.sub(r"^\([a-zA-Z0-9]+\)\s*", "", str(t)).strip()
            if is_filler_text(body):
                bad.append({"q": q.get("question_number"), "text": t})
        if q.get("chapter_id") not in allowed.allowed_chapter_ids:
            bad.append({"q": q.get("question_number"), "text": "chapter outside allowed set"})
    if bad:
        return _fail("MATCH_COLUMNS contains filler or out-of-syllabus pairs.", items=bad[:12])
    return _pass("MATCH_COLUMNS pairs are natural one-to-one book relationships.")


def _check_english_forbidden(items: list[dict], allowed: AllowedContentSet) -> dict:
    from .english_syllabus import FORBIDDEN_UNLESS_SYLLABUS

    allowed_blob = " ".join(allowed.allowed_item_names or []).lower()
    bad = []
    for q in items:
        if (q.get("content_class") or "").upper() != "LITERATURE" and (q.get("source_type") or "").lower() == "skill":
            continue
        blob = " ".join(
            [
                _qtext(q),
                q.get("passage") or "",
                q.get("extract") or "",
                q.get("choice_b") or "",
                " ".join(
                    (o.get("text") if isinstance(o, dict) else str(o))
                    for o in (q.get("options") or [])
                ),
                q.get("chapter_or_poem") or "",
            ]
        ).lower()
        for phrase in FORBIDDEN_UNLESS_SYLLABUS:
            if phrase in blob and phrase not in allowed_blob:
                bad.append({"q": q.get("question_number"), "phrase": phrase})
                break
    if bad:
        return _fail("Literature/text contains titles outside the active syllabus.", items=bad[:12])
    return _pass("Literature items stay inside the active syllabus.")


def report_text(report: dict) -> str:
    if str(report.get("subject") or "").lower() == "english":
        return _english_report_text(report)
    lines = ["EXAM VALIDATION REPORT", f"Overall: {report['overall']}", f"Status: {report['exam_status']}", ""]
    for name, rec in report["checks"].items():
        mark = "PASS" if rec["result"] == "PASS" else "FAIL"
        lines.append(f"[{mark}] {name}")
        lines.append(f"       {rec.get('detail')}")
    lines.append("")
    lines.append(f"Question count: {report['counts']['questions']}")
    lines.append(f"Total marks: {report['counts']['marks']}")
    lines.append(f"Out of syllabus: {report['counts']['out_of_syllabus']}")
    return "\n".join(lines)


def _english_report_text(report: dict) -> str:
    checks = report.get("checks") or {}
    counts = report.get("counts") or {}
    want = (checks.get("MARKS") or {}).get("detail") or ""
    lines = [
        "ENGLISH EXAM VALIDATION REPORT",
        f"TOTAL MARKS: {counts.get('marks')} / expected from profile",
        f"SYLLABUS: {(checks.get('CONTENT_GATE') or {}).get('result')}",
        f"FORMAT: {(checks.get('FORMAT') or {}).get('result')}",
        f"QUESTION SOURCES: Book {counts.get('book', 0)} | New {counts.get('new', 0)} | Skill {counts.get('skill', 0)}",
        f"OUT-OF-SYLLABUS QUESTIONS: {counts.get('out_of_syllabus', 0)}",
        f"MISSING/UNSUPPORTED SOURCES: {', '.join(report.get('missing_sources') or []) or 'none'}",
        f"DUPLICATES: {(checks.get('DUPLICATES') or {}).get('result')}",
        f"FINAL STATUS: {report.get('overall')} / {report.get('exam_status')}",
        "",
    ]
    for name, rec in checks.items():
        mark = "PASS" if rec["result"] == "PASS" else "FAIL"
        lines.append(f"[{mark}] {name}")
        lines.append(f"       {rec.get('detail')}")
    if want:
        lines.append("")
        lines.append(want)
    return "\n".join(lines)
