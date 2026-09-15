from __future__ import annotations

import json
import re
from collections import defaultdict

from .english_book_importer import load_english_book_index
from .english_content_gate import assert_english_question_allowed
from .english_print_cleanup import (
    EXTRACT_FORMATS,
    READING_FORMATS,
    exam_extract_text,
    looks_like_retrieval_dump,
    normalize_options,
    options_blob,
    sanitize_item,
    short_extract,
)
from .english_syllabus import FORBIDDEN_UNLESS_SYLLABUS, names_match
from .llm_client import chat_json, mock_mode, model_name
from .logger import get_logger
from .models import AllowedContentSet

log = get_logger("english_gen")


def _counted(slot: dict) -> int:
    v = slot.get("counted_marks")
    if v is None or v == "":
        return int(slot["marks"])
    return int(v)

SYSTEM = (
    "You generate Class 10 MPBSE-style English quarterly exam items. "
    "Student-facing text and answers MUST be English. "
    "Reading/Writing/Grammar are SKILL items: do not test First Flight chapter content. "
    "Literature items may use ONLY the allowed chapter/poem names and excerpts in the payload. "
    "Forbidden unless listed as allowed: A Tiger in the Zoo, A Triumph of Surgery, Tricki, "
    "Mrs Pumphrey, Footprints Without Feet, later First Flight chapters such as Anne Frank. "
    "BOOK literature: preserve the meaning of the supplied textbook question. "
    "NEW literature: write a fresh question answerable only from the supplied excerpt. "
    "The field excerpt is INTERNAL EVIDENCE only. Never copy the retrieved excerpt, "
    "BEFORE YOU READ, TO THE TEACHER, glossary, page headers, repeated titles, or "
    "warmup/activity text into question_text, passage, extract, or options. "
    "question_text is the student-facing question only. "
    "For LITERATURE_EXTRACT_MCQ set extract to a short 3-8 line quote from the excerpt "
    "and put the question in question_text. For other literature, passage and extract "
    "must be empty. Reading passages may be original unseen text only. "
    "Return JSON only: {\"items\":[...]} with keys: question_number, subquestion_number, "
    "format_id, marks, source_type, content_class, chapter_id, chapter_or_poem, "
    "source_pages, source_question_id, question_text, answer_key, options, passage, "
    "extract, choice_b, choice_b_answer, essay_topics, picture_prompt, generation_reason. "
    "options MUST be a JSON array of objects {\"label\":\"A\",\"text\":\"...\"} for A-D "
    "when the format is MCQ, else []. Never stringify dicts. "
    "source_type is book, new, or skill."
)

SECTION_HEADINGS = {
    "UNSEEN_PASSAGE_MCQ": "Read the following passage and answer the questions given below",
    "NOTE_MAKING": (
        "Read the following passage carefully and make notes on it using headings "
        "and sub-headings. Also provide a suitable title for your notes."
    ),
    "APPLICATION_OR_LETTER": "Writing",
    "ESSAY": "Write an essay on any ONE of the following topics.",
    "PICTURE_COMPOSITION": "Observe the picture below and describe the scene in about 60–75 words.",
    "GRAMMAR_FILL_BLANK": "Fill in the blanks choosing the correct options (any 5)",
    "DO_AS_DIRECTED": "Do as Directed (any 5)",
    "LITERATURE_EXTRACT_MCQ": "Read the extract carefully and answer the questions given below it",
    "LITERATURE_MCQ": "Choose the correct answer",
    "LITERATURE_SA_2": "Answer the following questions (any six)",
    "LITERATURE_POEM_SA": "Answer the following questions (any two)",
    "LITERATURE_SA_3": "Answer the following questions (any two)",
    "LITERATURE_LA_3": "Answer the following question",
}


def generate_english_exam(exam_config: dict, blueprint: dict, allowed: AllowedContentSet) -> tuple[dict, dict]:
    index = load_english_book_index()
    qmap = {q["question_id"]: q for q in index["questions"]}
    cmap = {c["chapter_id"]: c for c in index["chapters"]}
    usage = {
        "model": model_name(),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": 0.0,
        "calls": 0,
    }
    used_book: set[str] = set()
    prepared = []
    for slot in blueprint["slots"]:
        rec = dict(slot)
        rec["chapter"] = cmap.get(slot.get("chapter_id") or "", {})
        rec["book_question"] = None
        rec["excerpt"] = ""
        if rec.get("content_class") == "LITERATURE" and rec.get("chapter_id"):
            ch = cmap.get(rec["chapter_id"], {})
            rec["excerpt"] = _excerpt_for(index, rec["chapter_id"])
            rec["chapter_or_poem"] = ch.get("chapter_name")
        prepared.append(rec)

    extract_groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in prepared:
        if rec.get("format_id") in EXTRACT_FORMATS:
            extract_groups[(rec["question_number"], rec.get("sub_slot"))].append(rec)
    for recs in extract_groups.values():
        lead = recs[0]
        for rec in recs[1:]:
            rec["chapter_id"] = lead.get("chapter_id")
            rec["excerpt"] = lead.get("excerpt") or ""
            rec["chapter_or_poem"] = lead.get("chapter_or_poem")
            rec["chapter"] = lead.get("chapter") or {}
            rec["kind"] = lead.get("kind")

    for rec in prepared:
        if rec.get("content_class") == "LITERATURE" and rec.get("requested_source") == "book":
            bq = _pick_book_question(rec, allowed, qmap, used_book)
            if bq:
                used_book.add(bq["question_id"])
                rec["book_question"] = bq

    if mock_mode():
        items = [_fallback_item(s, allowed, qmap) for s in prepared]
    else:
        items = _llm_items(prepared, exam_config, allowed, usage)
        items = _repair_missing(items, prepared, exam_config, allowed, usage)

    by_key = {}
    for it in items:
        try:
            by_key[_slot_key(it.get("question_number"), it.get("subquestion_number"), it.get("sub_slot"))] = it
        except Exception:
            continue

    out = []
    for slot in prepared:
        key = _slot_key(slot["question_number"], slot.get("subquestion_number"), slot.get("sub_slot"))
        raw = by_key.get(key)
        rec = _normalize_item(raw, slot, allowed, qmap) if raw else _fallback_item(slot, allowed, qmap)
        if not (rec.get("question_text") or "").strip():
            rec = _fallback_item(slot, allowed, qmap)
        if rec.get("content_class") == "LITERATURE":
            reasons = assert_english_question_allowed(rec, allowed)
            if reasons or _forbidden_hit(rec, allowed):
                rec = _fallback_item(slot, allowed, qmap)
                rec["generation_reason"] = "replaced_out_of_syllabus"
        rec["section_heading"] = SECTION_HEADINGS.get(rec.get("format_id") or "", "")
        rec["syllabus_allowed"] = rec.get("content_class") != "LITERATURE" or not assert_english_question_allowed(rec, allowed)
        rec["validation_status"] = "pending"
        rec = sanitize_item(rec)
        out.append(rec)

    _unify_printed_extracts(out)
    out.sort(key=lambda x: (int(x["question_number"]), x.get("sub_slot") or "", _sub_order(x.get("subquestion_number"))))
    _dedupe_question_stems(out)
    header = {
        "school_line": "Jalta Sitara / School Examination",
        "exam_title": exam_config.get("exam_name") or "Grade 10 English Quarterly",
        "exam_type": blueprint.get("exam_type") or "Quarterly",
        "grade": 10,
        "subject": "English",
        "board": "MPBSE",
        "total_marks": blueprint["total_marks"],
        "duration_minutes": blueprint["duration_minutes"],
        "language_header": "en",
        "language_body": "en",
        "instructions": [
            "All questions are compulsory except where 'any N' or OR is printed.",
            "Section A: Reading (14 marks).",
            "Section B: Writing (13 marks).",
            "Section C: Grammar (10 marks).",
            "Section D: Literature from the printed syllabus only (43 marks).",
        ],
    }
    exam = {
        "exam_name": blueprint["exam_name"],
        "grade": 10,
        "subject": "English",
        "exam_type": blueprint["exam_type"],
        "difficulty": blueprint["difficulty"],
        "total_marks": blueprint["total_marks"],
        "duration_minutes": blueprint["duration_minutes"],
        "question_source": blueprint["question_source"],
        "header": header,
        "questions": out,
        "llm_usage": usage,
        "allowed_chapter_ids": list(allowed.allowed_chapter_ids),
        "allowed_item_names": list(allowed.allowed_item_names),
        "missing_sources": list(allowed.missing_sources),
        "syllabus": {"groups": list(allowed.syllabus_groups)},
    }
    log.info("Generated English exam items=%s usage=%s", len(out), usage)
    return exam, usage


def _excerpt_for(index: dict, chapter_id: str) -> str:
    for t in index["topics"]:
        if t["chapter_id"] == chapter_id and t.get("source_excerpt"):
            return (t["source_excerpt"] or "")[:1800]
    return ""


def _pick_book_question(slot: dict, allowed: AllowedContentSet, qmap: dict, used: set[str]) -> dict | None:
    cid = slot.get("chapter_id")
    cands = []
    for qid in allowed.eligible_book_question_ids:
        if qid in used:
            continue
        q = qmap.get(qid)
        if not q:
            continue
        if cid and q["chapter_id"] != cid:
            continue
        cands.append(q)
    if not cands:
        for qid in allowed.eligible_book_question_ids:
            if qid in used:
                continue
            q = qmap.get(qid)
            if q:
                cands.append(q)
    if not cands:
        return None
    fmt = slot.get("format_id") or ""
    if "POEM" in fmt:
        cands.sort(key=lambda q: 0 if q.get("kind") == "poem" else 1)
    return cands[0]


def _slot_key(qn, sub, sub_slot=None) -> tuple:
    n = int(str(qn).strip())
    if sub is None or sub == "" or str(sub).lower() in ("none", "null"):
        s = None
    else:
        s = str(sub).strip().lower().strip("(). ")
    ss = (str(sub_slot).lower() if sub_slot else "")
    if s and "-" in s:
        left, right = s.split("-", 1)
        if not ss:
            ss = left
        s = right
    return (n, s, ss)


def _sub_order(sub) -> int:
    order = {k: i for i, k in enumerate(["i", "ii", "iii", "iv", "v", "vi", "vii"])}
    if sub and "-" in str(sub):
        sub = str(sub).split("-", 1)[-1]
    return order.get(sub or "", 99)


def _unify_printed_extracts(items: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in items:
        if rec.get("format_id") in EXTRACT_FORMATS:
            groups[(rec.get("question_number"), rec.get("sub_slot"))].append(rec)
    for recs in groups.values():
        lead = recs[0]
        text = exam_extract_text(lead)
        for rec in recs:
            rec["extract"] = text
            rec["passage"] = text


def _dedupe_question_stems(items: list[dict]) -> None:
    seen: dict[str, dict] = {}
    for rec in items:
        text = (rec.get("question_text") or "").strip()
        key = re.sub(r"[^\w]+", "", text.lower())
        if len(key) < 12:
            continue
        if key not in seen:
            seen[key] = rec
            continue
        alt = text.replace("the passage", "this passage", 1)
        if re.sub(r"[^\w]+", "", alt.lower()) == key:
            alt = text.rstrip("? ") + ", based on the given text?"
        rec["question_text"] = alt
        seen[re.sub(r"[^\w]+", "", alt.lower())] = rec


def _llm_items(prepared: list[dict], exam_config: dict, allowed: AllowedContentSet, usage: dict) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in prepared:
        groups[rec["format_id"]].append(rec)
    items = []
    for fmt, recs in groups.items():
        payload = {
            "allowed_syllabus": allowed.allowed_item_names,
            "allowed_poems": allowed.allowed_poems,
            "allowed_prose": allowed.allowed_prose,
            "format_id": fmt,
            "slots": [
                {
                    "question_number": r["question_number"],
                    "subquestion_number": r.get("subquestion_number"),
                    "sub_slot": r.get("sub_slot"),
                    "marks": r["marks"],
                    "content_class": r["content_class"],
                    "requested_source": r["requested_source"],
                    "chapter_id": r.get("chapter_id"),
                    "chapter_or_poem": r.get("chapter_or_poem"),
                    "kind": r.get("kind"),
                    "internal_or": r.get("internal_or"),
                    "any_one_of": r.get("any_one_of"),
                    "book_question": (
                        {
                            "question_id": r["book_question"]["question_id"],
                            "question_text": r["book_question"]["question_text"][:500],
                            "source_page": r["book_question"]["source_page"],
                            "chapter_or_poem": r["book_question"].get("chapter_or_poem"),
                        }
                        if r.get("book_question")
                        else None
                    ),
                    "excerpt": (r.get("excerpt") or "")[:900],
                }
                for r in recs
            ],
        }
        user = "Generate exactly these slots. Do not add extra items.\n" + json.dumps(payload, ensure_ascii=False)
        usage["calls"] = usage.get("calls", 0) + 1
        data = chat_json(SYSTEM, user, usage_acc=usage)
        batch = data.get("items") or data.get("questions") or []
        if isinstance(batch, dict):
            batch = [batch]
        items.extend(batch)
    return items


def _repair_missing(items: list[dict], prepared: list[dict], exam_config: dict, allowed: AllowedContentSet, usage: dict) -> list[dict]:
    have = set()
    for i in items:
        try:
            have.add(_slot_key(i.get("question_number"), i.get("subquestion_number"), i.get("sub_slot")))
        except Exception:
            continue
    missing = [s for s in prepared if _slot_key(s["question_number"], s.get("subquestion_number"), s.get("sub_slot")) not in have]
    if not missing:
        return items
    log.warning("Repairing %s missing English items", len(missing))
    extra = _llm_items(missing, exam_config, allowed, usage)
    return items + extra


def _as_text(val) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return " | ".join(str(x) for x in val)
    if isinstance(val, dict):
        for k in ("stem", "question_text", "text", "question", "answer_key", "answer"):
            if val.get(k):
                return str(val[k]).strip()
        return ""
    return str(val)


def _normalize_item(it: dict, slot: dict, allowed: AllowedContentSet, qmap: dict) -> dict:
    cls = slot.get("content_class") or "LITERATURE"
    requested = (slot.get("requested_source") or "new").lower()
    src = requested
    if cls in ("READING", "WRITING", "GRAMMAR"):
        src = "skill"
    bq = slot.get("book_question")
    chapter_id = it.get("chapter_id") or slot.get("chapter_id")
    name = it.get("chapter_or_poem") or slot.get("chapter_or_poem") or ""
    pages = it.get("source_pages") or []
    if isinstance(pages, int):
        pages = [pages]
    sqid = it.get("source_question_id")
    if src == "book" and bq:
        chapter_id = bq["chapter_id"]
        name = bq.get("chapter_or_poem") or name
        pages = [bq["source_page"]] if bq.get("source_page") else pages
        sqid = bq["question_id"]
        src = "book"
    if src == "new" and slot.get("excerpt"):
        sqid = None
        if slot.get("chapter"):
            pages = pages or [slot["chapter"].get("start_page")]
    options = it.get("options") or []
    if not isinstance(options, list):
        options = [options]
    options = normalize_options(options)
    qtext = _as_text(it.get("question_text") or it.get("question_text_hindi"))
    if looks_like_retrieval_dump(qtext):
        qtext = ""
    if src == "book" and bq and (not qtext or len(qtext) < 8):
        qtext = bq["question_text"]
    kind = slot.get("kind") or (slot.get("chapter") or {}).get("kind") or ""
    extract_in = _as_text(it.get("extract"))
    passage_in = _as_text(it.get("passage"))
    excerpt = slot.get("excerpt") or ""
    fmt = slot["format_id"]
    if fmt in EXTRACT_FORMATS:
        extract = short_extract(extract_in or passage_in or excerpt, kind, name)
        passage = extract
    elif fmt in READING_FORMATS:
        extract = ""
        passage = "" if looks_like_retrieval_dump(passage_in) else passage_in
    else:
        extract = ""
        passage = ""
    out = {
        "question_number": int(slot["question_number"]),
        "subquestion_number": slot.get("subquestion_number"),
        "sub_slot": slot.get("sub_slot"),
        "format_id": slot["format_id"],
        "marks": int(slot["marks"]),
        "counted_marks": _counted(slot),
        "content_class": cls,
        "source_type": src,
        "chapter_id": chapter_id,
        "topic_ids": [bq.get("topic_ids", [None])[0]] if bq and bq.get("topic_ids") else [],
        "chapter_or_poem": name,
        "book_name": "First Flight" if cls == "LITERATURE" else None,
        "source_pages": [int(p) for p in pages if str(p).isdigit() or isinstance(p, int)],
        "source_question_id": sqid,
        "source_page_or_locator": (pages[0] if pages else None),
        "question_text": qtext,
        "answer_key": _as_text(it.get("answer_key") or it.get("answer_key_hindi") or it.get("answer")) or "Mark for content, organisation, and accuracy as per the given task.",
        "options": options,
        "passage": passage,
        "extract": extract,
        "source_context": excerpt[:1800] if cls == "LITERATURE" else "",
        "kind": kind or None,
        "choice_b": _as_text(it.get("choice_b")),
        "choice_b_answer": _as_text(it.get("choice_b_answer")),
        "essay_topics": it.get("essay_topics") if isinstance(it.get("essay_topics"), list) else [],
        "picture_prompt": _as_text(it.get("picture_prompt")),
        "format_rule": slot.get("format_id"),
        "generation_reason": _as_text(it.get("generation_reason")) or (
            "book_question" if bq and src == "book" else requested
        ),
        "syllabus_allowed": True,
        "attempt_any": slot.get("attempt_any"),
        "internal_or": slot.get("internal_or"),
    }
    if not out["source_pages"] and slot.get("chapter"):
        sp = slot["chapter"].get("start_page")
        if sp:
            out["source_pages"] = [sp]
            out["source_page_or_locator"] = sp
    return out


def _forbidden_hit(rec: dict, allowed: AllowedContentSet) -> bool:
    blob = " ".join(
        [
            rec.get("question_text") or "",
            rec.get("passage") or "",
            rec.get("extract") or "",
            rec.get("choice_b") or "",
            options_blob(rec.get("options") or []),
        ]
    ).lower()
    allowed_l = " ".join(allowed.allowed_item_names).lower()
    for phrase in FORBIDDEN_UNLESS_SYLLABUS:
        if phrase in blob and phrase not in allowed_l:
            return True
    return False


def _fallback_item(slot: dict, allowed: AllowedContentSet, qmap: dict) -> dict:
    cls = slot.get("content_class") or "LITERATURE"
    bq = slot.get("book_question")
    ch = slot.get("chapter") or {}
    name = slot.get("chapter_or_poem") or ch.get("chapter_name") or (allowed.allowed_item_names[0] if allowed.allowed_item_names else "")
    if cls == "LITERATURE" and bq:
        qtext = bq["question_text"]
        src = "book"
        sqid = bq["question_id"]
        pages = [bq["source_page"]]
        ans = "Answer from the First Flight text named in the question."
    elif cls == "LITERATURE":
        qtext = f"With reference to '{name}', explain a key idea from the allowed text."
        src = "new"
        sqid = None
        pages = [ch.get("start_page")] if ch.get("start_page") else []
        ans = f"The answer must come from {name} in First Flight."
    elif slot["format_id"] == "UNSEEN_PASSAGE_MCQ":
        qtext = "According to the passage, which option is correct?"
        src = "skill"
        sqid = None
        pages = []
        ans = "(b)"
    elif slot["format_id"] == "NOTE_MAKING":
        qtext = "Make suitable notes on the given passage with a title and sub-headings."
        src = "skill"
        sqid = None
        pages = []
        ans = "Title + heading/sub-heading notes covering the main points of the passage."
    elif slot["format_id"] == "APPLICATION_OR_LETTER":
        qtext = "Write an application to your Principal requesting books from the book-bank."
        src = "skill"
        sqid = None
        pages = []
        ans = "Formal application: sender address, date, Principal, subject, request, closing."
    elif slot["format_id"] == "ESSAY":
        qtext = "Write an essay on any one of the given topics."
        src = "skill"
        sqid = None
        pages = []
        ans = "Introduction, 2-3 body points, conclusion; relevant to the chosen topic."
    elif slot["format_id"] == "PICTURE_COMPOSITION":
        qtext = "Write 60-75 words about the described scene."
        src = "skill"
        sqid = None
        pages = []
        ans = "A short paragraph covering people, place, and action in the scene."
    elif slot["format_id"] == "GRAMMAR_FILL_BLANK":
        qtext = "We ____ follow the traffic rules. (should / may / can)"
        src = "skill"
        sqid = None
        pages = []
        ans = "should"
    else:
        qtext = "She cut the tree. (Change into interrogative)"
        src = "skill"
        sqid = None
        pages = []
        ans = "Did she cut the tree?"
    kind = slot.get("kind") or ch.get("kind") or ""
    excerpt = slot.get("excerpt") or ""
    fmt = slot["format_id"]
    if fmt in EXTRACT_FORMATS:
        extract = short_extract(excerpt, kind, name)
        passage = extract
    elif cls == "READING":
        extract = ""
        passage = (
            "Trees along roads give shade to travellers. Planned planting of suitable trees "
            "makes highways safer and more pleasant. Careless mixing of trees often spoils the avenue."
        )
    else:
        extract = ""
        passage = ""
    rec = {
        "question_number": slot["question_number"],
        "subquestion_number": slot.get("subquestion_number"),
        "sub_slot": slot.get("sub_slot"),
        "format_id": slot["format_id"],
        "marks": slot["marks"],
        "counted_marks": _counted(slot),
        "content_class": cls,
        "source_type": src,
        "chapter_id": slot.get("chapter_id"),
        "topic_ids": [],
        "chapter_or_poem": name if cls == "LITERATURE" else None,
        "book_name": "First Flight" if cls == "LITERATURE" else None,
        "source_pages": [p for p in pages if p],
        "source_question_id": sqid,
        "source_page_or_locator": pages[0] if pages else None,
        "question_text": qtext,
        "answer_key": ans,
        "options": [
            {"label": "A", "text": "Kashmir"},
            {"label": "B", "text": "Kerala"},
            {"label": "C", "text": "Karnataka"},
            {"label": "D", "text": "Kanyakumari"},
        ] if fmt == "UNSEEN_PASSAGE_MCQ" else [],
        "passage": passage,
        "extract": extract,
        "source_context": excerpt[:1800] if cls == "LITERATURE" else "",
        "kind": kind or None,
        "choice_b": "Write a letter to your friend inviting him to your birthday party." if slot["format_id"] == "APPLICATION_OR_LETTER" else (
            f"Describe how '{name}' presents a central idea of the lesson." if slot.get("internal_or") and cls == "LITERATURE" else ""
        ),
        "choice_b_answer": "Informal letter with invitation details." if slot["format_id"] == "APPLICATION_OR_LETTER" else (
            f"Answer from {name}." if slot.get("internal_or") and cls == "LITERATURE" else ""
        ),
        "essay_topics": [
            "Importance of sports",
            "Science: a blessing or a curse",
            "An Indian festival",
            "Online education",
        ] if slot["format_id"] == "ESSAY" else [],
        "picture_prompt": "A classroom in which students are planting a sapling in the school garden." if slot["format_id"] == "PICTURE_COMPOSITION" else "",
        "format_rule": slot.get("format_id"),
        "generation_reason": "fallback",
        "syllabus_allowed": True,
        "attempt_any": slot.get("attempt_any"),
        "internal_or": slot.get("internal_or"),
    }
    return rec
