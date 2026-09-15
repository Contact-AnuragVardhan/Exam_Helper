from __future__ import annotations

from collections import defaultdict

from .blueprint_builder import load_formats, load_profile
from .logger import get_logger
from .models import AllowedContentSet


log = get_logger("english_blueprint")

SUB_LABELS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]


def build_english_blueprint(exam_config: dict, allowed: AllowedContentSet) -> dict:
    profile = load_profile("english")
    formats = {f["format_id"]: f for f in load_formats("english")["formats"]}
    structure = profile["question_structure"]
    total_marks = int(exam_config.get("total_marks") or profile["default_total_marks"])
    duration = int(exam_config.get("duration_minutes") or profile["default_duration_minutes"])
    source = (exam_config.get("question_source") or profile["question_source_default"]).upper()
    if source == "BOOK":
        book_percent, new_percent = 100, 0
    elif source == "NEW":
        book_percent, new_percent = 0, 100
    else:
        source = "MIXED"
        book_percent = int(exam_config.get("book_percent", 70))
        new_percent = 100 - book_percent

    if total_marks != structure["total_marks"]:
        raise ValueError(
            f"English quarterly profile is {structure['total_marks']} marks; got {total_marks}."
        )

    warnings = list(allowed.warnings)
    prose = list(allowed.allowed_prose or allowed.allowed_chapter_ids)
    poems = list(allowed.allowed_poems or [])
    ch_cycle = list(allowed.allowed_chapter_ids) or ["skill"]
    pr = 0
    pm = 0

    slots = []
    for group in structure["groups"]:
        n_sub = int(group.get("subquestion_count") or 1)
        labels = SUB_LABELS[:n_sub] if n_sub > 1 else [None]
        src_class = group.get("source_class") or "SKILL"
        kind = (group.get("kind") or "").lower()
        for lab in labels:
            lab_out = f"{group['sub_slot']}-{lab}" if group.get("sub_slot") and lab else lab
            if src_class == "SKILL":
                req = "skill"
                cid = None
            else:
                req = "book" if source in ("BOOK", "MIXED") else "new"
                if kind == "poem" and poems:
                    cid = _id_for_name(allowed, poems[pm % len(poems)])
                    pm += 1
                elif (kind == "prose" or not kind) and (prose or ch_cycle):
                    pool = prose or ch_cycle
                    name_or_id = pool[pr % len(pool)]
                    cid = _id_for_name(allowed, name_or_id) if name_or_id not in allowed.allowed_chapter_ids else name_or_id
                    if cid is None:
                        cid = ch_cycle[pr % len(ch_cycle)]
                    pr += 1
                else:
                    cid = ch_cycle[0] if ch_cycle else None
                    req = "new" if source == "NEW" else "book"
            slots.append(
                {
                    "question_number": group["question_number"],
                    "subquestion_number": lab_out,
                    "sub_slot": group.get("sub_slot"),
                    "section_id": group["section_id"],
                    "content_class": group["content_class"],
                    "format_id": group["format_id"],
                    "marks": group["marks_each"],
                    "attempt_any": group.get("attempt_any"),
                    "internal_or": bool(group.get("internal_or")),
                    "any_one_of": group.get("any_one_of"),
                    "kind": kind or None,
                    "chapter_id": cid,
                    "requested_source": req,
                    "source_class": src_class,
                    "format_name": formats.get(group["format_id"], {}).get("format_name", group["format_id"]),
                    "counted_marks": group["marks_each"] if not group.get("attempt_any") else (
                        group["marks_each"] if labels.index(lab) < int(group.get("attempt_any") or n_sub) else 0
                    ),
                }
            )

    # Marks: attempt_any extras are printed but do not count toward the total.
    counted = 0
    by_q: dict[int, list[dict]] = defaultdict(list)
    for s in slots:
        by_q[s["question_number"]].append(s)
    for group in structure["groups"]:
        counted += int(group["total_marks"])

    blueprint = {
        "exam_name": exam_config.get("exam_name") or "Grade 10 English Quarterly",
        "grade": 10,
        "subject": "English",
        "exam_type": exam_config.get("exam_type") or "Quarterly",
        "difficulty": exam_config.get("difficulty") or "default",
        "total_marks": total_marks,
        "duration_minutes": duration,
        "question_source": source,
        "book_percent": book_percent,
        "new_percent": new_percent,
        "allowed_chapter_ids": list(allowed.allowed_chapter_ids),
        "allowed_topic_ids": list(allowed.allowed_topic_ids),
        "allowed_item_names": list(allowed.allowed_item_names),
        "allowed_prose": list(allowed.allowed_prose),
        "allowed_poems": list(allowed.allowed_poems),
        "missing_sources": list(allowed.missing_sources),
        "syllabus_groups": list(allowed.syllabus_groups),
        "sections": structure.get("sections") or [],
        "eligible_book_question_count": len(allowed.eligible_book_question_ids),
        "slot_count": len(slots),
        "slots": slots,
        "counted_marks": counted,
        "format_summary": _format_summary(slots),
        "warnings": warnings,
        "internal_choice": {"enabled": True, "status": "from_school_qe"},
    }
    log.info("English blueprint source=%s slots=%s marks=%s", source, len(slots), counted)
    return blueprint


def _id_for_name(allowed: AllowedContentSet, name_or_id: str) -> str | None:
    if name_or_id in allowed.allowed_chapter_ids:
        return name_or_id
    from .english_book_importer import load_english_book_index
    from .english_syllabus import names_match

    index = load_english_book_index()
    for c in index["chapters"]:
        if names_match(c["chapter_name"], str(name_or_id)) and c["chapter_id"] in allowed.allowed_chapter_ids:
            return c["chapter_id"]
    return None


def _format_summary(slots: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for s in slots:
        rec = agg.setdefault(
            s["format_id"],
            {"format_id": s["format_id"], "count": 0, "book": 0, "new": 0, "skill": 0},
        )
        rec["count"] += 1
        rec[s["requested_source"]] = rec.get(s["requested_source"], 0) + 1
    return list(agg.values())


def print_english_blueprint(blueprint: dict) -> str:
    lines = [
        "=" * 64,
        "ENGLISH EXAM BLUEPRINT",
        "=" * 64,
        f"Name: {blueprint['exam_name']}",
        f"GRADE: {blueprint['grade']}",
        f"SUBJECT: {blueprint['subject']}",
        f"EXAM TYPE: {blueprint['exam_type']}",
        "BOOK: First Flight",
        "SYLLABUS: Q1 / Quarterly",
        f"QUESTION SOURCE: {blueprint['question_source']}",
        f"Marks: {blueprint['total_marks']}   Duration: {blueprint['duration_minutes']} min",
        "",
        "ACTIVE SYLLABUS",
    ]
    for g in blueprint.get("syllabus_groups") or []:
        lines.append(f"  {g.get('book')}:")
        for it in g.get("items") or []:
            lines.append(f"    • {it}")
    lines.append("Allowed chapters: " + ", ".join(blueprint.get("allowed_prose") or []))
    lines.append("Allowed poems: " + ", ".join(blueprint.get("allowed_poems") or []))
    lines.append("")
    lines.append("SECTIONS / MARKS")
    for sec in blueprint.get("sections") or []:
        lines.append(f"  Section {sec.get('section_id')} {sec.get('name')}: {sec.get('marks')} marks")
    lines.append("")
    lines.append("PLANNED QUESTION TYPES")
    for rec in blueprint["format_summary"]:
        lines.append(
            f"  {rec['format_id']:26s} items={rec['count']:2d} "
            f"book={rec.get('book', 0)} new={rec.get('new', 0)} skill={rec.get('skill', 0)}"
        )
    if blueprint.get("missing_sources"):
        lines.append("")
        lines.append("MISSING/UNSUPPORTED SOURCES")
        for m in blueprint["missing_sources"]:
            lines.append(f"  - MISSING BOOK SOURCE: {m}")
    if blueprint["warnings"]:
        lines.append("")
        lines.append("WARNINGS")
        for w in blueprint["warnings"]:
            lines.append(f"  - {w}")
    lines.append("=" * 64)
    return "\n".join(lines)
