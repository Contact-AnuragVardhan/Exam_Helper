from __future__ import annotations

from .english_book_importer import load_english_book_index
from .english_syllabus import item_allowed, load_active_english_syllabus, names_match
from .logger import get_logger
from .models import AllowedContentSet


log = get_logger("english_gate")


def build_english_allowed_content(exam_config: dict | None = None) -> AllowedContentSet:
    syllabus = load_active_english_syllabus(exam_config)
    index = load_english_book_index()
    chapters = index["chapters"]
    topics = index["topics"]
    questions = index["questions"]
    warnings = list(syllabus.get("missing_books") and [
        f"MISSING BOOK SOURCE: {b}" for b in syllabus.get("missing_books") or []
    ] or [])

    allowed_ch = []
    allowed_names = []
    prose = []
    poems = []
    for c in chapters:
        if item_allowed(c["chapter_name"], syllabus):
            allowed_ch.append(c["chapter_id"])
            allowed_names.append(c["chapter_name"])
            if c.get("kind") == "poem":
                poems.append(c["chapter_name"])
            else:
                prose.append(c["chapter_name"])

    # also allow sub-story topics (His First Flight / Black Aeroplane) when parent chapter allowed
    allowed_ch_set = set(allowed_ch)
    allowed_topics = [t["topic_id"] for t in topics if t["chapter_id"] in allowed_ch_set]
    page_ranges = []
    for c in chapters:
        if c["chapter_id"] in allowed_ch_set:
            page_ranges.append(
                {
                    "chapter_id": c["chapter_id"],
                    "topic_id": None,
                    "start_page": c["start_page"],
                    "end_page": c["end_page"],
                }
            )

    eligible = []
    for q in questions:
        if not q.get("examinable"):
            continue
        if q["chapter_id"] not in allowed_ch_set:
            continue
        eligible.append(q["question_id"])

    if not eligible:
        warnings.append("No eligible First Flight questions inside the active syllabus.")

    groups = []
    for g in syllabus.get("groups") or []:
        if g["book"] in (syllabus.get("missing_books") or []):
            groups.append({"book": g["book"], "items": ["[MISSING BOOK SOURCE] — literature not generated from this book"]})
        else:
            groups.append({"book": g["book"], "items": list(g.get("items") or [])})

    acs = AllowedContentSet(
        allowed_chapter_ids=allowed_ch,
        allowed_topic_ids=allowed_topics,
        allowed_page_ranges=page_ranges,
        eligible_book_question_ids=eligible,
        warnings=warnings,
        subject="English",
        allowed_item_names=allowed_names or list(syllabus.get("all_items") or []),
        allowed_prose=prose or list(syllabus.get("prose") or []),
        allowed_poems=poems or list(syllabus.get("poems") or []),
        missing_sources=list(syllabus.get("missing_books") or []),
        syllabus_groups=groups,
    )
    log.info(
        "English content gate: items=%s eligible_book_questions=%s missing=%s",
        acs.allowed_item_names,
        len(acs.eligible_book_question_ids),
        acs.missing_sources,
    )
    return acs


def _literature_name_allowed(name: str, allowed: AllowedContentSet) -> bool:
    if not name:
        return True
    if any(names_match(name, x) for x in allowed.allowed_item_names):
        return True
    if names_match(name, "His First Flight") or names_match(name, "Black Aeroplane"):
        return any(names_match("Two Stories about Flying", x) for x in allowed.allowed_item_names)
    return False


def assert_english_question_allowed(question: dict, allowed: AllowedContentSet) -> list[str]:
    cls = (question.get("content_class") or "").upper()
    src = (question.get("source_type") or "").lower()
    if src == "skill" or cls in ("READING", "WRITING", "GRAMMAR"):
        return []
    fails = []
    name = question.get("chapter_or_poem") or ""
    cid = question.get("chapter_id")
    if cid and cid not in allowed.allowed_chapter_ids:
        fails.append(f"literature chapter_id {cid} is not in allowed syllabus set")
    if name and allowed.allowed_item_names and not _literature_name_allowed(name, allowed):
        fails.append(f"chapter_or_poem '{name}' is not in the active syllabus")
    pages = question.get("source_pages") or []
    if pages and src in ("book", "new"):
        ok = False
        for p in pages:
            for rng in allowed.allowed_page_ranges:
                try:
                    if rng["start_page"] <= int(p) <= rng["end_page"]:
                        ok = True
                        break
                except Exception:
                    continue
            if ok:
                break
        if not ok:
            fails.append(f"source_pages {pages} are outside allowed First Flight ranges")
    if src in ("book", "book_adapted"):
        sqid = question.get("source_question_id")
        if sqid and sqid not in allowed.eligible_book_question_ids:
            fails.append(f"source_question_id {sqid} is not in eligible First Flight set")
    return fails
