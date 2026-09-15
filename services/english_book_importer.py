from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from .english_print_cleanup import literary_excerpt
from .logger import get_logger
from .paths import book_data_dir, source_path


log = get_logger("english_book")

BOOK_ID = "ncert_class10_first_flight"
NOISE = {"reprint 2026-27", "first flight", "contents"}

CONTENTS_UNITS = [
    {"name": "A Letter to God", "kind": "prose", "start_page": 1, "unit": 1},
    {"name": "Dust of Snow", "kind": "poem", "start_page": 14, "unit": 1},
    {"name": "Fire and Ice", "kind": "poem", "start_page": 15, "unit": 1},
    {"name": "Nelson Mandela: Long Walk to Freedom", "kind": "prose", "start_page": 16, "unit": 2},
    {"name": "A Tiger in the Zoo", "kind": "poem", "start_page": 29, "unit": 2},
    {"name": "Two Stories about Flying", "kind": "prose", "start_page": 32, "unit": 3},
    {"name": "How to Tell Wild Animals", "kind": "poem", "start_page": 43, "unit": 3},
    {"name": "The Ball Poem", "kind": "poem", "start_page": 46, "unit": 3},
    {"name": "From the Diary of Anne Frank", "kind": "prose", "start_page": 48, "unit": 4},
    {"name": "Amanda!", "kind": "poem", "start_page": 61, "unit": 4},
    {"name": "Glimpses of India", "kind": "prose", "start_page": 63, "unit": 5},
    {"name": "The Trees", "kind": "poem", "start_page": 77, "unit": 5},
    {"name": "Mijbil the Otter", "kind": "prose", "start_page": 80, "unit": 6},
    {"name": "Fog", "kind": "poem", "start_page": 93, "unit": 6},
    {"name": "Madam Rides the Bus", "kind": "prose", "start_page": 94, "unit": 7},
    {"name": "The Tale of Custard the Dragon", "kind": "poem", "start_page": 107, "unit": 7},
    {"name": "The Sermon at Benares", "kind": "prose", "start_page": 111, "unit": 8},
    {"name": "For Anne Gregory", "kind": "poem", "start_page": 118, "unit": 8},
    {"name": "The Proposal", "kind": "prose", "start_page": 120, "unit": 9},
]

STOP_HEADINGS = (
    "thinking about language",
    "what we have done",
    "what you can do",
    "before you read",
    "in this lesson",
    "speaking",
    "listening",
    "writing",
)


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line or "").strip()


def _page_text(page) -> str:
    return page.get_text("text") or ""


def detect_english_offset(doc) -> int:
    for i in range(min(20, doc.page_count)):
        t = _page_text(doc[i])
        if "BEFORE YOU READ" in t and "Lencho" in t:
            return i  # pdf_index = book_page + offset - 1
    return 12


def pdf_index_for_book_page(book_page: int, offset: int) -> int:
    return book_page + offset - 1


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s[:40]


def _is_examinable_question(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 12:
        return False
    low = t.lower()
    if low.startswith("look at the following"):
        return False
    if "fill out the money order" in low:
        return False
    if low.startswith(("i was not", "when my comrades", "to reassure me", "the basic and honourable")):
        return False
    if len(t.split()) < 4:
        return False
    if re.match(r"^[ivx]+\.\s+look at", low):
        return False
    return "?" in t or t.lower().startswith(("who", "what", "why", "how", "where", "when", "which", "did", "does", "do", "can", "describe", "explain", "discuss", "are there", "there are"))


def _extract_numbered_questions(block: str) -> list[str]:
    raw_lines = [_clean(x) for x in (block or "").splitlines()]
    lines: list[str] = []
    i = 0
    while i < len(raw_lines):
        ln = raw_lines[i]
        if not ln or ln.lower() in NOISE:
            i += 1
            continue
        m = re.match(r"^(\d+)\.\s*$", ln)
        if m and i + 1 < len(raw_lines) and raw_lines[i + 1]:
            lines.append(f"{m.group(1)}. {raw_lines[i + 1]}")
            i += 2
            continue
        lines.append(ln)
        i += 1
    parts: list[str] = []
    current = None
    buf: list[str] = []
    for ln in lines:
        low = ln.lower()
        if any(low.startswith(h) for h in STOP_HEADINGS):
            break
        if re.match(r"^thinking about (the )?(text|poem|language)\b", low):
            break
        if re.match(r"^oral comprehension check\b", low):
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", ln)
        if m and int(m.group(1)) <= 20:
            if current is not None:
                q = " ".join(buf).strip()
                if q:
                    parts.append(q)
            current = m.group(1)
            buf = [m.group(2)]
        elif current is not None:
            if re.match(r"^[IVX]+\.\s+", ln):
                break
            if ln.lower().startswith("what we have done"):
                break
            buf.append(ln)
    if current is not None:
        q = " ".join(buf).strip()
        if q:
            parts.append(q)
    return [p for p in parts if _is_examinable_question(p)]


def _unit_end_page(i: int, last_page: int) -> int:
    if i + 1 < len(CONTENTS_UNITS):
        return CONTENTS_UNITS[i + 1]["start_page"] - 1
    return last_page


def import_english_book(force: bool = False) -> dict:
    out_dir = book_data_dir("english")
    out_dir.mkdir(parents=True, exist_ok=True)
    book_json = out_dir / "book.json"
    if book_json.exists() and not force:
        log.info("English book index already exists at %s", book_json)
        return json.loads(book_json.read_text(encoding="utf-8"))

    pdf_path = source_path("english_book_pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(f"English book PDF not found: {pdf_path}")

    log.info("Importing English narrative book from %s", pdf_path)
    doc = fitz.open(str(pdf_path))
    offset = detect_english_offset(doc)
    last_book_page = max(1, doc.page_count - offset + 1)

    chapters = []
    topics = []
    questions = []
    qn = 0

    for i, unit in enumerate(CONTENTS_UNITS):
        start = int(unit["start_page"])
        end = _unit_end_page(i, last_book_page)
        cid = f"ff_{_slug(unit['name'])}"
        chapter = {
            "chapter_id": cid,
            "chapter_number": i + 1,
            "chapter_name": unit["name"],
            "kind": unit["kind"],
            "book_name": "First Flight",
            "unit_number": unit["unit"],
            "start_page": start,
            "end_page": end,
            "topics": [],
            "exercises": [],
        }
        tid = f"{cid}_body"
        excerpt_parts = []
        page_blocks = []
        for bp in range(start, end + 1):
            idx = pdf_index_for_book_page(bp, offset)
            if idx < 0 or idx >= doc.page_count:
                continue
            raw = _page_text(doc[idx])
            page_blocks.append((bp, raw))
            keep = []
            for ln in raw.splitlines():
                cl = _clean(ln)
                if not cl or cl.lower() in NOISE:
                    continue
                if cl.isdigit():
                    continue
                keep.append(cl)
            excerpt_parts.append(" ".join(keep))
        excerpt = literary_excerpt(" ".join(excerpt_parts), unit["name"], unit["kind"])
        topic = {
            "topic_id": tid,
            "chapter_id": cid,
            "section_number": str(unit["unit"]),
            "topic_name": unit["name"],
            "kind": unit["kind"],
            "start_page": start,
            "end_page": end,
            "source_excerpt": excerpt[:4000],
        }
        chapter["topics"].append(tid)
        topics.append(topic)

        if unit["name"] == "Two Stories about Flying":
            for sub_name, key in (("His First Flight", "his first flight"), ("Black Aeroplane", "black aeroplane")):
                sub_tid = f"{cid}_{_slug(sub_name)}"
                topics.append(
                    {
                        "topic_id": sub_tid,
                        "chapter_id": cid,
                        "section_number": str(unit["unit"]),
                        "topic_name": sub_name,
                        "kind": "prose",
                        "start_page": start,
                        "end_page": end,
                        "source_excerpt": literary_excerpt(excerpt, sub_name, "prose")[:4000],
                    }
                )
                chapter["topics"].append(sub_tid)

        full = "\n".join(t for _, t in page_blocks)
        chunks = re.split(
            r"(?=Oral Comprehension Check|Thinking about the Text|Thinking about the Poem)",
            full,
            flags=re.I,
        )
        for ch in chunks:
            head = ch[:80].lower()
            if "oral comprehension check" in head:
                source_kind = "oral_comprehension"
            elif "thinking about the poem" in head:
                source_kind = "thinking_about_the_poem"
            elif "thinking about the text" in head:
                source_kind = "thinking_about_the_text"
            else:
                continue
            for qt in _extract_numbered_questions(ch):
                qn += 1
                qid = f"eq_{cid}_{qn:03d}"
                src_page = start
                for bp, raw in page_blocks:
                    if qt[:40] in re.sub(r"\s+", " ", raw):
                        src_page = bp
                        break
                questions.append(
                    {
                        "question_id": qid,
                        "chapter_id": cid,
                        "topic_ids": [tid],
                        "chapter_or_poem": unit["name"],
                        "kind": unit["kind"],
                        "book_name": "First Flight",
                        "question_text": qt,
                        "source_page": src_page,
                        "source_kind": source_kind,
                        "examinable": True,
                    }
                )
        got_here = [q for q in questions if q["chapter_id"] == cid]
        if not got_here:
            for qt in _extract_numbered_questions(full):
                qn += 1
                qid = f"eq_{cid}_{qn:03d}"
                src_page = start
                for bp, raw in page_blocks:
                    if qt[:32] in re.sub(r"\s+", " ", raw):
                        src_page = bp
                        break
                questions.append(
                    {
                        "question_id": qid,
                        "chapter_id": cid,
                        "topic_ids": [tid],
                        "chapter_or_poem": unit["name"],
                        "kind": unit["kind"],
                        "book_name": "First Flight",
                        "question_text": qt,
                        "source_page": src_page,
                        "source_kind": "unit_questions",
                        "examinable": True,
                    }
                )
        chapters.append(chapter)

    book = {
        "book_id": BOOK_ID,
        "title": "First Flight, Textbook in English for Class X (NCERT)",
        "grade": 10,
        "subject": "English",
        "language": "en",
        "book_structure": "narrative",
        "source_pdf": str(pdf_path),
        "pdf_page_count": doc.page_count,
        "book_page_offset": offset,
        "chapters": [c["chapter_id"] for c in chapters],
        "status": "READY",
        "warnings": [],
        "counts": {
            "chapters": len(chapters),
            "topics": len(topics),
            "book_questions": len(questions),
            "examinable_questions": sum(1 for q in questions if q.get("examinable")),
        },
    }
    (out_dir / "book.json").write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "chapters.json").write_text(
        json.dumps({"chapters": chapters, "exercises": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "topics.json").write_text(json.dumps({"topics": topics}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "book_questions.json").write_text(
        json.dumps({"questions": questions}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    doc.close()
    log.info(
        "English index ready chapters=%s questions=%s examinable=%s",
        len(chapters),
        len(questions),
        book["counts"]["examinable_questions"],
    )
    return book


def load_english_book_index() -> dict:
    d = book_data_dir("english")
    if not (d / "book.json").exists():
        import_english_book(force=True)
    return {
        "book": json.loads((d / "book.json").read_text(encoding="utf-8")),
        "chapters": json.loads((d / "chapters.json").read_text(encoding="utf-8"))["chapters"],
        "topics": json.loads((d / "topics.json").read_text(encoding="utf-8"))["topics"],
        "questions": json.loads((d / "book_questions.json").read_text(encoding="utf-8"))["questions"],
    }


if __name__ == "__main__":
    import_english_book(force=True)
