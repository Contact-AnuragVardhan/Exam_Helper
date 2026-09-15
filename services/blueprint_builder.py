from __future__ import annotations

from collections import defaultdict

from .logger import get_logger
from .models import AllowedContentSet
from .paths import ROOT, load_json, exam_profile_path, formats_path
from .book_importer import load_book_index


log = get_logger("blueprint")

SUB_LABELS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]


def load_profile(subject: str | None = None) -> dict:
    return load_json(exam_profile_path(subject))


def load_formats(subject: str | None = None) -> dict:
    return load_json(formats_path(subject))


def _split_count(n: int, book_percent: int) -> tuple[int, int]:
    if n <= 0:
        return 0, 0
    book_n = int(round(n * book_percent / 100.0))
    book_n = min(n, max(0, book_n))
    return book_n, n - book_n


def build_blueprint(exam_config: dict, allowed: AllowedContentSet) -> dict:
    profile = load_profile()
    formats = {f["format_id"]: f for f in load_formats()["formats"]}
    index = load_book_index()
    qmap = {q["question_id"]: q for q in index["questions"]}

    total_marks = int(exam_config.get("total_marks") or profile["default_total_marks"])
    duration = int(exam_config.get("duration_minutes") or profile["default_duration_minutes"])
    source = (exam_config.get("question_source") or profile["question_source_default"]).upper()
    book_percent = int(exam_config.get("book_percent", 50 if source == "MIXED" else (100 if source == "BOOK" else 0)))
    new_percent = int(exam_config.get("new_percent", 100 - book_percent))
    if source == "BOOK":
        book_percent, new_percent = 100, 0
    elif source == "NEW":
        book_percent, new_percent = 0, 100
    if book_percent + new_percent != 100:
        raise ValueError("book_percent + new_percent must equal 100.")

    structure = profile["question_structure"]
    if total_marks != structure["total_marks"]:
        # Do not invent a new MPBSE pattern. Pilot uses the 75-mark structure only.
        raise ValueError(
            f"Build #1 only supports the supplied 75-mark Q1-Q23 structure. "
            f"Configured total_marks={total_marks} is not supported without an explicit format table."
        )

    warnings = list(allowed.warnings)
    weightage_status = profile["chapter_weightage_status"]
    if weightage_status != "verified":
        warnings.append(
            "Class 10 Mathematics chapter weightage is not_supplied_or_not_verified. "
            "Slots are allocated with equal round-robin across selected chapters. "
            "No fabricated weights were used."
        )

    chapters_cycle = list(allowed.allowed_chapter_ids)
    if not chapters_cycle:
        raise ValueError("Allowed content set has no chapters.")

    eligible_by_ch: dict[str, list[str]] = defaultdict(list)
    for qid in allowed.eligible_book_question_ids:
        q = qmap.get(qid)
        if q:
            eligible_by_ch[q["chapter_id"]].append(qid)

    slots = []
    rr = 0
    for group in structure["groups"]:
        fmt_id = group["format_id"]
        labels = SUB_LABELS[: group["subquestion_count"]] if group["subquestion_count"] > 1 else [None]
        n_items = len(group["question_numbers"]) * len(labels)
        book_n, new_n = _split_count(n_items, book_percent)
        sources = ["book"] * book_n + ["new"] * new_n
        si = 0
        for qn in group["question_numbers"]:
            for lab in labels:
                ch = chapters_cycle[rr % len(chapters_cycle)]
                rr += 1
                src = sources[si]
                si += 1
                slots.append(
                    {
                        "question_number": qn,
                        "subquestion_number": lab,
                        "format_id": fmt_id,
                        "marks": group["marks_each"],
                        "chapter_id": ch,
                        "requested_source": src,
                        "format_name": formats.get(fmt_id, {}).get("format_name", fmt_id),
                    }
                )

    book_marks = sum(s["marks"] for s in slots if s["requested_source"] == "book")
    new_marks = sum(s["marks"] for s in slots if s["requested_source"] == "new")
    eligible_count = len(allowed.eligible_book_question_ids)
    book_slots = sum(1 for s in slots if s["requested_source"] == "book")
    if source in ("BOOK", "MIXED") and eligible_count < book_slots:
        warnings.append(
            f"Eligible book questions ({eligible_count}) < BOOK slots ({book_slots}). "
            "Generator may reuse a source concept as book_adapted or fail those slots."
        )

    blueprint = {
        "exam_name": exam_config.get("exam_name") or "Grade 10 Mathematics Test",
        "grade": 10,
        "subject": "Mathematics",
        "exam_type": exam_config.get("exam_type") or "Custom",
        "difficulty": exam_config.get("difficulty") or "default",
        "total_marks": total_marks,
        "duration_minutes": duration,
        "question_source": source,
        "book_percent": book_percent,
        "new_percent": new_percent,
        "allowed_chapter_ids": list(allowed.allowed_chapter_ids),
        "allowed_topic_ids": list(allowed.allowed_topic_ids),
        "chapter_weightage_status": weightage_status,
        "chapter_weightage_source": "unverified" if weightage_status != "verified" else "mpbse",
        "neutral_allocation_strategy": profile["neutral_allocation_strategy"],
        "eligible_book_question_count": eligible_count,
        "eligible_book_questions_by_chapter": {k: len(v) for k, v in eligible_by_ch.items()},
        "requested_book_marks": book_marks,
        "requested_new_marks": new_marks,
        "slot_count": len(slots),
        "slots": slots,
        "format_summary": _format_summary(slots),
        "warnings": warnings,
        "internal_choice": profile.get("internal_choice"),
    }
    log.info(
        "Blueprint: source=%s slots=%s book_marks=%s new_marks=%s weightage=%s",
        source,
        len(slots),
        book_marks,
        new_marks,
        weightage_status,
    )
    return blueprint


def _format_summary(slots: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for s in slots:
        rec = agg.setdefault(
            s["format_id"],
            {"format_id": s["format_id"], "count": 0, "marks": 0, "book": 0, "new": 0},
        )
        rec["count"] += 1
        rec["marks"] += s["marks"]
        rec[s["requested_source"]] += 1
    return list(agg.values())


def print_blueprint(blueprint: dict) -> str:
    lines = []
    lines.append("=" * 64)
    lines.append("EXAM BLUEPRINT")
    lines.append("=" * 64)
    lines.append(f"Name: {blueprint['exam_name']}")
    lines.append(f"Type: {blueprint['exam_type']}   Difficulty: {blueprint['difficulty']}")
    lines.append(f"Marks: {blueprint['total_marks']}   Duration: {blueprint['duration_minutes']} min")
    lines.append(
        f"Source: {blueprint['question_source']}  "
        f"(Book {blueprint['book_percent']}% / New {blueprint['new_percent']}%)"
    )
    lines.append(f"Allowed chapters: {', '.join(blueprint['allowed_chapter_ids'])}")
    lines.append(f"Eligible book questions: {blueprint['eligible_book_question_count']}")
    lines.append(
        f"Chapter weightage: {blueprint['chapter_weightage_status']} "
        f"(source={blueprint['chapter_weightage_source']})"
    )
    lines.append("Allocation: " + blueprint["neutral_allocation_strategy"]["id"])
    lines.append("")
    lines.append("FORMAT COUNTS")
    for rec in blueprint["format_summary"]:
        lines.append(
            f"  {rec['format_id']:22s} items={rec['count']:2d} marks={rec['marks']:2d} "
            f"book={rec['book']} new={rec['new']}"
        )
    lines.append("")
    lines.append(
        f"Requested marks: book={blueprint['requested_book_marks']} "
        f"new={blueprint['requested_new_marks']}"
    )
    if blueprint["warnings"]:
        lines.append("")
        lines.append("WARNINGS")
        for w in blueprint["warnings"]:
            lines.append(f"  - {w}")
    lines.append("=" * 64)
    return "\n".join(lines)
