from __future__ import annotations

import json
import re
from collections import defaultdict

from .book_importer import load_book_index
from .content_gate import assert_question_allowed
from .llm_client import chat_json, mock_mode, model_name
from .logger import get_logger
from .models import AllowedContentSet
from .match_columns import build_match_question
from .paths import load_json, formats_path


log = get_logger("generator")

SECTION_HEADINGS = {
    "MCQ": "सही विकल्प चुनकर लिखिए",
    "FILL_BLANK": "रिक्त स्थानों की पूर्ति कीजिए",
    "TRUE_FALSE": "सत्य / असत्य लिखिए",
    "MATCH_COLUMNS": "सही जोड़ी बनाइए",
    "ONE_WORD_OR_SENTENCE": "एक वाक्य में उत्तर दीजिए",
    "VERY_SHORT_2_MARK": "अति लघु उत्तरीय प्रश्न",
    "SHORT_3_MARK": "लघु उत्तरीय प्रश्न",
    "LONG_4_MARK": "दीर्घ उत्तरीय प्रश्न",
}

SYSTEM = (
    "You generate Class 10 MPBSE Mathematics exam items. "
    "Student-facing question text and answers MUST be Hindi (Devanagari). "
    "Keep mathematical symbols, variables, and formulae unchanged. "
    "Use ONLY the allowed sources in the user payload. "
    "Never test Circles, Trigonometry, Statistics, Probability, or any chapter not listed. "
    "Return JSON only: {\"items\":[...]} with keys: "
    "question_number, subquestion_number, format_id, marks, difficulty, "
    "source_type, chapter_id, topic_ids, source_pages, source_question_id, "
    "question_text_hindi, answer_key_hindi, options, match_column_a, match_column_b. "
    "options is a 4-list for MCQ only, else []. "
    "BOOK/book_adapted: preserve the mathematical meaning of the given textbook item; "
    "do not invent a new problem and label it as a book question. "
    "Because the textbook extract is English, translated Hindi items must use source_type=book_adapted "
    "and keep source_question_id. "
    "MATCH_COLUMNS BOOK is NOT built from a single exercise. Use only natural one-to-one "
    "book facts. Forbidden filler Column A/B words: multiply, expand, equation, calculation, "
    "verification, equality, गुणा, विस्तार, समीकरण, गणना, सत्यापन. "
    "If a book exercise is a solve/prove/find problem, do not convert it into MATCH. "
    "NEW: new numbers/context allowed; concept must come from supplied excerpts; source_type=new; "
    "source_pages must be from the excerpt. "
    "Each answer_key_hindi must actually answer that item."
)


def _index_maps() -> tuple[dict, dict, dict]:
    index = load_book_index()
    qmap = {q["question_id"]: q for q in index["questions"]}
    cmap = {c["chapter_id"]: c for c in index["chapters"]}
    tmap = {t["topic_id"]: t for t in index["topics"]}
    return qmap, cmap, tmap


def _format_fit_score(qtext: str, format_id: str) -> int:
    t = qtext.lower()
    if format_id == "LONG_4_MARK":
        return 5 if any(w in t for w in ("prove", "show that", "nature of the root", "solve the following pair")) else 1
    if format_id == "SHORT_3_MARK":
        return 4 if any(w in t for w in ("verify", "relationship", "quadratic polynomial", "zeroes")) else 1
    if format_id == "VERY_SHORT_2_MARK":
        return 3 if any(w in t for w in ("find", "solve", "zero", "hcf", "lcm")) else 1
    return 1


def _pick_book_question(
    slot: dict,
    allowed: AllowedContentSet,
    qmap: dict,
    used: set[str],
) -> dict | None:
    ch = slot["chapter_id"]
    candidates = []
    for qid in allowed.eligible_book_question_ids:
        if qid in used:
            continue
        q = qmap.get(qid)
        if not q or q["chapter_id"] != ch:
            continue
        candidates.append(q)
    if not candidates:
        for qid in allowed.eligible_book_question_ids:
            if qid in used:
                continue
            q = qmap.get(qid)
            if q:
                candidates.append(q)
    if not candidates:
        qid = next(iter(allowed.eligible_book_question_ids), None)
        return qmap.get(qid) if qid else None
    candidates.sort(key=lambda q: -_format_fit_score(q.get("question_text") or "", slot["format_id"]))
    return candidates[0]


def _topic_payload(chapter_id: str, tmap: dict, allowed: AllowedContentSet, limit: int = 2) -> list[dict]:
    topics = [
        tmap[tid]
        for tid in allowed.allowed_topic_ids
        if tid in tmap and tmap[tid]["chapter_id"] == chapter_id
    ]
    topics = [t for t in topics if t["topic_name"].lower() != "summary"]
    out = []
    for t in topics[:limit]:
        out.append(
            {
                "topic_id": t["topic_id"],
                "topic_name": t["topic_name"],
                "start_page": t["start_page"],
                "end_page": t["end_page"],
                "excerpt": (t.get("source_excerpt") or "")[:1200],
            }
        )
    return out


def generate_exam(exam_config: dict, blueprint: dict, allowed: AllowedContentSet) -> tuple[dict, dict]:
    qmap, cmap, tmap = _index_maps()
    formats = {f["format_id"]: f for f in load_json(formats_path())["formats"]}
    usage = {"model": model_name(), "prompt_tokens": 0, "completion_tokens": 0, "estimated_cost_usd": 0.0, "calls": 0}
    used_book: set[str] = set()

    prepared = []
    for slot in blueprint["slots"]:
        rec = dict(slot)
        if slot["requested_source"] == "book" and slot["format_id"] != "MATCH_COLUMNS":
            bq = _pick_book_question(slot, allowed, qmap, used_book)
            if bq:
                used_book.add(bq["question_id"])
                rec["book_question"] = {
                    "question_id": bq["question_id"],
                    "question_text": bq["question_text"][:800],
                    "source_page": bq["source_page"],
                    "chapter_id": bq["chapter_id"],
                    "topic_ids": bq.get("topic_ids") or [],
                    "exercise_number": bq.get("exercise_number"),
                }
            rec["topics"] = _topic_payload(slot["chapter_id"], tmap, allowed, limit=1)
        elif slot["requested_source"] == "book" and slot["format_id"] == "MATCH_COLUMNS":
            rec["book_question"] = None
            rec["topics"] = _topic_payload(slot["chapter_id"], tmap, allowed, limit=1)
        else:
            rec["book_question"] = None
            rec["topics"] = _topic_payload(slot["chapter_id"], tmap, allowed, limit=2)
        prepared.append(rec)

    llm_prepared = [
        r for r in prepared
        if not (r["format_id"] == "MATCH_COLUMNS" and r["requested_source"] == "book")
    ]
    if mock_mode():
        items = _mock_items(llm_prepared, exam_config, qmap, cmap)
    else:
        items = _llm_items(llm_prepared, exam_config, formats, usage) if llm_prepared else []
        items = _repair_missing(items, llm_prepared, exam_config, formats, usage) if llm_prepared else items

    by_key = {}
    for i in items:
        try:
            by_key[_slot_key(i.get("question_number"), i.get("subquestion_number"))] = i
        except (TypeError, ValueError):
            continue
    items = []
    for slot in prepared:
        if slot.get("format_id") == "MATCH_COLUMNS" and slot.get("requested_source") == "book":
            items.append(
                {
                    "question_number": slot["question_number"],
                    "subquestion_number": slot["subquestion_number"],
                    "format_id": "MATCH_COLUMNS",
                    "marks": slot["marks"],
                    "source_type": "book",
                    "question_text_hindi": "सही जोड़ी बनाइए",
                    "answer_key_hindi": "",
                }
            )
            continue
        key = (slot["question_number"], slot["subquestion_number"])
        raw = by_key.get(key)
        if raw is None:
            rec = _fallback_item(slot, allowed, qmap)
        else:
            rec = _normalize_item(raw, slot, allowed, qmap)
        if not rec.get("question_text_hindi"):
            rec = _fallback_item(slot, allowed, qmap)
        items.append(rec)

    items = _apply_book_match_tables(items, prepared, allowed)
    _uniquify_stems(items)
    items.sort(key=lambda x: (int(x["question_number"]), SUB_ORDER.get(x.get("subquestion_number") or "", 99)))
    header = {
        "school_line": "Jalta Sitara / School Examination",
        "exam_title": exam_config.get("exam_name") or blueprint.get("exam_name") or "Grade 10 Mathematics",
        "exam_type": blueprint.get("exam_type"),
        "grade": 10,
        "subject": "Mathematics",
        "board": "MPBSE",
        "total_marks": blueprint["total_marks"],
        "duration_minutes": blueprint["duration_minutes"],
        "language_header": "en",
        "language_body": "hi",
        "instructions": [
            "All questions are compulsory.",
            "Questions 1-5: objective, 1 mark each sub-question.",
            "Questions 6-17: very short answer, 2 marks each.",
            "Questions 18-20: short answer, 3 marks each.",
            "Questions 21-23: long answer, 4 marks each.",
        ],
    }
    exam = {
        "exam_name": blueprint["exam_name"],
        "grade": 10,
        "subject": "Mathematics",
        "exam_type": blueprint["exam_type"],
        "difficulty": blueprint["difficulty"],
        "total_marks": blueprint["total_marks"],
        "duration_minutes": blueprint["duration_minutes"],
        "question_source": blueprint["question_source"],
        "header": header,
        "questions": items,
        "llm_usage": usage,
        "allowed_chapter_ids": list(allowed.allowed_chapter_ids),
    }
    for it in items:
        it["section_heading"] = SECTION_HEADINGS.get(it.get("format_id") or "", "")
        it["validation_status"] = "pending"
    log.info("Generated %s items usage=%s", len(items), usage)
    return exam, usage


SUB_ORDER = {k: i for i, k in enumerate(["i", "ii", "iii", "iv", "v", "vi"])}


def _slot_key(question_number, subquestion_number) -> tuple:
    qn = int(str(question_number).strip())
    if subquestion_number is None or subquestion_number == "" or str(subquestion_number).lower() in ("none", "null"):
        return (qn, None)
    sub = str(subquestion_number).strip().lower()
    sub = sub.strip("(). ")
    return (qn, sub)


def _apply_book_match_tables(items: list[dict], prepared: list[dict], allowed: AllowedContentSet) -> list[dict]:
    from collections import defaultdict

    grouped: dict[int, list[int]] = defaultdict(list)
    for i, slot in enumerate(prepared):
        if slot.get("format_id") == "MATCH_COLUMNS" and slot.get("requested_source") == "book":
            grouped[int(slot["question_number"])].append(i)
    if not grouped:
        return items
    used: set[str] = set()
    for qn, idxs in grouped.items():
        table = build_match_question(allowed, n_pairs=len(idxs), used_ids=used, seed=1000 + qn)
        for j, idx in enumerate(idxs):
            slot = prepared[idx]
            pair = table["pairs"][j]
            items[idx] = {
                "question_number": int(slot["question_number"]),
                "subquestion_number": slot["subquestion_number"],
                "format_id": "MATCH_COLUMNS",
                "marks": int(slot["marks"]),
                "difficulty": "default",
                "source_type": "book",
                "chapter_id": pair["chapter_id"],
                "topic_ids": [pair["topic_id"]],
                "source_pages": [pair["source_page"]],
                "source_question_id": pair["pair_id"],
                "source_ref": pair["source_ref"],
                "question_text_hindi": pair["a_hi"] if j else "सही जोड़ी बनाइए",
                "answer_key_hindi": f"{pair['a_hi']} → {pair['b_hi']}  ({table['answer_mapping'][j]})",
                "options": [],
                "match_column_a": table["column_a"] if j == 0 else [],
                "match_column_b": table["column_b"] if j == 0 else [],
                "match_pairs": table["pairs"] if j == 0 else [],
                "answer_mapping": table["answer_mapping"] if j == 0 else [],
                "validation_status": "pending",
            }
    return items
    qn = int(str(question_number).strip())
    if subquestion_number is None or subquestion_number == "" or str(subquestion_number).lower() in ("none", "null"):
        return (qn, None)
    sub = str(subquestion_number).strip().lower()
    sub = sub.strip("(). ")
    return (qn, sub)


def _align(items: list[dict], prepared: list[dict]) -> list[dict]:
    by_key = {}
    for it in items:
        key = (int(it.get("question_number") or 0), it.get("subquestion_number"))
        by_key[key] = it
    out = []
    for slot in prepared:
        key = (slot["question_number"], slot["subquestion_number"])
        if key in by_key:
            out.append(by_key[key])
    return out


def _llm_items(prepared: list[dict], exam_config: dict, formats: dict, usage: dict) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in prepared:
        groups[(rec["format_id"],)].append(rec)
    items = []
    for (fmt,), recs in groups.items():
        payload = {
            "difficulty": exam_config.get("difficulty") or "default",
            "format_id": fmt,
            "format_brief": {
                "marks": formats.get(fmt, {}).get("marks"),
                "student_task": formats.get(fmt, {}).get("student_task"),
                "wording_constraints": formats.get(fmt, {}).get("wording_constraints"),
            },
            "slots": [
                {
                    "question_number": r["question_number"],
                    "subquestion_number": r["subquestion_number"],
                    "marks": r["marks"],
                    "chapter_id": r["chapter_id"],
                    "book_question": r.get("book_question"),
                    "topics": r.get("topics"),
                }
                for r in recs
            ],
        }
        user = (
            "Generate exactly these slots. Do not add extra items.\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        usage["calls"] = usage.get("calls", 0) + 1
        data = chat_json(SYSTEM, user, usage_acc=usage)
        batch = data.get("items") or data.get("questions") or []
        if isinstance(batch, dict):
            batch = [batch]
        items.extend(batch)
    return items


def _repair_missing(items: list[dict], prepared: list[dict], exam_config: dict, formats: dict, usage: dict) -> list[dict]:
    have = {_slot_key(i.get("question_number"), i.get("subquestion_number")) for i in items if i.get("question_number") is not None}
    missing = [s for s in prepared if (s["question_number"], s["subquestion_number"]) not in have]
    if not missing:
        return items
    log.warning("Repairing %s missing generated items", len(missing))
    extra = _llm_items(missing, exam_config, formats, usage)
    return items + extra


def _as_text(val) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        parts = []
        for x in val:
            if isinstance(x, dict):
                parts.append(json.dumps(x, ensure_ascii=False))
            else:
                parts.append(str(x))
        return " | ".join(parts)
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def _normalize_item(it: dict, slot: dict, allowed: AllowedContentSet, qmap: dict) -> dict:
    requested = (slot.get("requested_source") or "new").lower()
    src = requested
    if src == "book":
        src = "book_adapted"
    chapter_id = it.get("chapter_id") or slot["chapter_id"]
    topic_ids = it.get("topic_ids") or []
    if isinstance(topic_ids, str):
        topic_ids = [topic_ids]
    source_pages = it.get("source_pages") or []
    if isinstance(source_pages, int):
        source_pages = [source_pages]
    bq = slot.get("book_question")
    sqid = it.get("source_question_id") or (bq or {}).get("question_id")
    if src in ("book", "book_adapted") and bq:
        chapter_id = bq["chapter_id"]
        topic_ids = bq.get("topic_ids") or topic_ids
        source_pages = [bq["source_page"]] if bq.get("source_page") else source_pages
        sqid = bq["question_id"]
        src = "book_adapted"
    if src == "new":
        sqid = None
        chapter_id = slot["chapter_id"]
        topics = slot.get("topics") or []
        allowed_topic_ids = [t["topic_id"] for t in topics]
        topic_ids = [t for t in topic_ids if t in allowed_topic_ids] or allowed_topic_ids[:1]
        if topics:
            source_pages = [topics[0]["start_page"], topics[0]["end_page"]]
    options = it.get("options") or []
    if not isinstance(options, list):
        options = [str(options)]
    else:
        options = [x if isinstance(x, str) else str(x) for x in options]
    out = {
        "question_number": int(slot["question_number"]),
        "subquestion_number": slot["subquestion_number"],
        "format_id": slot["format_id"],
        "marks": int(slot["marks"]),
        "difficulty": (it.get("difficulty") or "default"),
        "source_type": src,
        "chapter_id": chapter_id,
        "topic_ids": topic_ids,
        "source_pages": [int(p) for p in source_pages if str(p).isdigit() or isinstance(p, int)],
        "source_question_id": sqid,
        "question_text_hindi": _as_text(it.get("question_text_hindi") or it.get("question_text")),
        "answer_key_hindi": _as_text(it.get("answer_key_hindi") or it.get("answer")),
        "options": options,
        "match_column_a": it.get("match_column_a") or [],
        "match_column_b": it.get("match_column_b") or [],
        "validation_status": "pending",
    }
    if not out["source_pages"] and slot.get("topics"):
        out["source_pages"] = [slot["topics"][0]["start_page"]]
    return out


def _uniquify_stems(items: list[dict]) -> None:
    seen: dict[str, int] = {}
    for q in items:
        raw = q.get("question_text_hindi") or ""
        key = re.sub(r"\s+", "", raw).lower()
        if len(key) < 12:
            continue
        if key in seen:
            tag = f" [प्र.{q.get('question_number')}"
            if q.get("subquestion_number"):
                tag += f"({q.get('subquestion_number')})"
            tag += "]"
            q["question_text_hindi"] = raw + tag
        else:
            seen[key] = 1


def _fallback_item(slot: dict, allowed: AllowedContentSet, qmap: dict) -> dict:
    bq = slot.get("book_question")
    topics = slot.get("topics") or []
    if slot["requested_source"] == "book" and bq:
        text = "निम्नलिखित प्रश्न हल कीजिए (पुस्तक से अनुकूलित): " + bq["question_text"]
        return {
            "question_number": slot["question_number"],
            "subquestion_number": slot["subquestion_number"],
            "format_id": slot["format_id"],
            "marks": slot["marks"],
            "difficulty": "default",
            "source_type": "book_adapted",
            "chapter_id": bq["chapter_id"],
            "topic_ids": bq.get("topic_ids") or [],
            "source_pages": [bq["source_page"]],
            "source_question_id": bq["question_id"],
            "question_text_hindi": text[:1200],
            "answer_key_hindi": "उत्तर पुस्तक समाधान / कार्य से मिलान करें।",
            "options": [],
            "match_column_a": [],
            "match_column_b": [],
            "validation_status": "pending",
        }
    excerpt = (topics[0]["excerpt"][:180] if topics else "")
    return {
        "question_number": slot["question_number"],
        "subquestion_number": slot["subquestion_number"],
        "format_id": slot["format_id"],
        "marks": slot["marks"],
        "difficulty": "default",
        "source_type": "new",
        "chapter_id": slot["chapter_id"],
        "topic_ids": [topics[0]["topic_id"]] if topics else [],
        "source_pages": [topics[0]["start_page"]] if topics else [],
        "source_question_id": None,
        "question_text_hindi": "इस पाठ्यांश पर आधारित प्रश्न लिखिए: " + excerpt,
        "answer_key_hindi": "पाठ्य पुस्तक अवधारणा के अनुसार उत्तर दें।",
        "options": [],
        "match_column_a": [],
        "match_column_b": [],
        "validation_status": "pending",
    }


def _mock_items(prepared: list[dict], exam_config: dict, qmap: dict, cmap: dict) -> list[dict]:
    items = []
    for slot in prepared:
        items.append(_fallback_item(slot, None, qmap))  # type: ignore
    return items
