from __future__ import annotations

from .book_importer import load_book_index
from .logger import get_logger
from .models import AllowedContentSet


log = get_logger("content_gate")


def _chapter_id(n: int) -> str:
    return f"ch{int(n):02d}"


def build_allowed_content(
    allowed_chapter_numbers: list[int],
    allowed_topic_ids: list[str] | None = None,
    excluded_question_ids: list[str] | None = None,
) -> AllowedContentSet:
    """Return the only content the generator may use."""
    index = load_book_index()
    chapters = {c["chapter_id"]: c for c in index["chapters"]}
    topics = index["topics"]
    questions = index["questions"]
    excluded = set(excluded_question_ids or [])
    warnings: list[str] = []

    if not allowed_chapter_numbers:
        raise ValueError("At least one allowed chapter is required.")

    allowed_ch_ids = []
    for n in allowed_chapter_numbers:
        cid = _chapter_id(n)
        if cid not in chapters:
            raise ValueError(f"Chapter {n} is not in the imported book index.")
        allowed_ch_ids.append(cid)

    allowed_ch_set = set(allowed_ch_ids)
    topic_pool = [t for t in topics if t["chapter_id"] in allowed_ch_set]
    if allowed_topic_ids:
        wanted = set(allowed_topic_ids)
        unknown = wanted - {t["topic_id"] for t in topic_pool}
        if unknown:
            raise ValueError(f"Topic ids not inside selected chapters: {sorted(unknown)}")
        allowed_topics = [t for t in topic_pool if t["topic_id"] in wanted]
    else:
        allowed_topics = topic_pool
    allowed_topic_ids_out = [t["topic_id"] for t in allowed_topics]
    topic_set = set(allowed_topic_ids_out)

    page_ranges = []
    if allowed_topic_ids:
        for t in allowed_topics:
            page_ranges.append(
                {
                    "chapter_id": t["chapter_id"],
                    "topic_id": t["topic_id"],
                    "start_page": t["start_page"],
                    "end_page": t["end_page"],
                }
            )
    else:
        for cid in allowed_ch_ids:
            c = chapters[cid]
            page_ranges.append(
                {
                    "chapter_id": cid,
                    "topic_id": None,
                    "start_page": c["start_page"],
                    "end_page": c["end_page"],
                }
            )

    eligible = []
    for q in questions:
        if q["question_id"] in excluded:
            continue
        if not q.get("examinable", False):
            continue
        if q["chapter_id"] not in allowed_ch_set:
            continue
        q_topics = set(q.get("topic_ids") or [])
        if allowed_topic_ids and q_topics and q_topics.isdisjoint(topic_set):
            continue
        eligible.append(q["question_id"])

    if not eligible:
        warnings.append("No eligible examinable book questions in the allowed portion.")

    acs = AllowedContentSet(
        allowed_chapter_ids=allowed_ch_ids,
        allowed_topic_ids=allowed_topic_ids_out,
        allowed_page_ranges=page_ranges,
        eligible_book_question_ids=eligible,
        excluded_question_ids=sorted(excluded),
        warnings=warnings,
    )
    log.info(
        "Content gate: chapters=%s topics=%s eligible_book_questions=%s",
        acs.allowed_chapter_ids,
        len(acs.allowed_topic_ids),
        len(acs.eligible_book_question_ids),
    )
    return acs


def _allowed_as_lists(allowed: AllowedContentSet | dict) -> tuple[list[str], list[str]]:
    if hasattr(allowed, "allowed_chapter_ids"):
        return list(allowed.allowed_chapter_ids), list(allowed.allowed_topic_ids)
    return list(allowed.get("allowed_chapter_ids") or []), list(allowed.get("allowed_topic_ids") or [])


def build_syllabus_display(
    allowed: AllowedContentSet | dict,
    exam_config: dict | None = None,
) -> dict:
    """Student-facing syllabus for THIS exam, matching the content-gate allowed set."""
    if exam_config and str(exam_config.get("subject") or "").lower() == "english":
        groups = None
        if hasattr(allowed, "syllabus_groups"):
            groups = allowed.syllabus_groups
        elif isinstance(allowed, dict):
            groups = allowed.get("syllabus_groups")
        if groups:
            return {"groups": groups}
    ch_ids, topic_ids = _allowed_as_lists(allowed)
    index = load_book_index()
    book_title = (index.get("book") or {}).get("title") or "Textbook"
    chapters = {c["chapter_id"]: c for c in index["chapters"]}
    topics_by_id = {t["topic_id"]: t for t in index["topics"]}
    explicit_topics = bool(exam_config and exam_config.get("allowed_topic_ids"))

    items: list[str] = []
    if explicit_topics:
        for tid in topic_ids:
            t = topics_by_id.get(tid)
            if t and t.get("topic_name"):
                items.append(t["topic_name"])
    else:
        for cid in ch_ids:
            c = chapters.get(cid)
            if c and c.get("chapter_name"):
                items.append(c["chapter_name"])

    return {"groups": [{"book": book_title, "items": items}]}


def syllabus_display_from_exam(exam: dict) -> dict:
    syn = exam.get("syllabus")
    if isinstance(syn, dict) and syn.get("groups"):
        return syn
    ch_ids = list(exam.get("allowed_chapter_ids") or [])
    if not ch_ids:
        return {"groups": []}
    return build_syllabus_display(
        {"allowed_chapter_ids": ch_ids, "allowed_topic_ids": exam.get("allowed_topic_ids") or []},
        exam_config={"allowed_topic_ids": exam.get("allowed_topic_ids") or None},
    )


def assert_question_allowed(question: dict, allowed: AllowedContentSet) -> list[str]:
    """Return hard-fail reasons if a generated/selected item is outside the gate."""
    src = (question.get("source_type") or "").lower()
    cls = (question.get("content_class") or "").upper()
    if src == "skill" or cls in ("READING", "WRITING", "GRAMMAR"):
        return []
    if (getattr(allowed, "subject", None) or "").lower() == "english" or cls == "LITERATURE":
        from .english_content_gate import assert_english_question_allowed

        return assert_english_question_allowed(question, allowed)
    fails = []
    cid = question.get("chapter_id")
    if cid not in allowed.allowed_chapter_ids:
        fails.append(f"chapter_id {cid} is not in allowed set {allowed.allowed_chapter_ids}")
    q_topics = question.get("topic_ids") or []
    if q_topics and allowed.allowed_topic_ids:
        if set(q_topics).isdisjoint(set(allowed.allowed_topic_ids)):
            fails.append(f"topic_ids {q_topics} do not intersect allowed topics")
    pages = question.get("source_pages") or []
    if pages:
        ok = False
        for p in pages:
            for rng in allowed.allowed_page_ranges:
                if rng["start_page"] <= int(p) <= rng["end_page"]:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            fails.append(f"source_pages {pages} are outside allowed page ranges")
    src = (question.get("source_type") or "").lower()
    if src in ("book", "book_adapted"):
        if question.get("format_id") == "MATCH_COLUMNS" and question.get("source_ref"):
            return fails
        sqid = question.get("source_question_id")
        if not sqid:
            fails.append("book/book_adapted question missing source_question_id")
        elif sqid not in allowed.eligible_book_question_ids:
            fails.append(f"source_question_id {sqid} is not in eligible book question set")
    return fails
