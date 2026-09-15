from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from .logger import get_logger
from .paths import book_data_dir, source_path, ROOT, load_json, exam_profile_path


log = get_logger("book_importer")

BOOK_ID = "ncert_class10_mathematics_reprint_2026_27"
NOISE_LINES = {
    "reprint 2026-27",
    "mathematics",
    "not from the examination point of view.",
    "* not from the examination point of view.",
    "* these exercises are not from the examination point of view.",
}

CHAPTER_TITLE_RE = re.compile(
    r"^(REAL NUMBERS|POLYNOMIALS|PAIR OF LINEAR EQUATIONS IN TWO VARIABLES|"
    r"QUADRATIC EQUATIONS|ARITHMETIC PROGRESSIONS|TRIANGLES|COORDINATE GEOMETRY|"
    r"INTRODUCTION TO TRIGONOMETRY|SOME APPLICATIONS OF TRIGONOMETRY|CIRCLES|"
    r"AREAS RELATED TO CIRCLES|SURFACE AREAS AND VOLUMES|STATISTICS|PROBABILITY)$"
)

EXERCISE_RE = re.compile(
    r"(?m)^EXERCISE\s+(\d+)\.(\d+)(?:\s*\((Optional)\*?\))?",
)
SECTION_RE = re.compile(r"^(\d+)\.(\d+)\s+(.+)$")
EXAMPLE_RE = re.compile(r"^Example\s+(\d+)\s*:", re.IGNORECASE)
QUESTION_START_RE = re.compile(r"^(\d+)\.\s+(.*)$")
STAR_QUESTION_RE = re.compile(r"^\*")


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _page_lines(page) -> list[str]:
    text = page.get_text("text") or ""
    return [_clean_line(x) for x in text.splitlines() if _clean_line(x)]


def _is_noise(line: str) -> bool:
    low = line.lower().strip(" *")
    if low in NOISE_LINES:
        return True
    if re.fullmatch(r"\d+", line):
        return True
    if line.lower().startswith("fig."):
        return True
    return False


def detect_page_offset(doc) -> tuple[int, list[str]]:
    """Find PDF page index of printed book page 1 (REAL NUMBERS start)."""
    warnings = []
    for i in range(min(30, doc.page_count)):
        lines = _page_lines(doc[i])
        joined = " ".join(lines[:8]).upper()
        if "REAL NUMBERS" in joined and any(x == "1" for x in lines[:6]):
            # printed page 1 at pdf index i => offset = i (pdf_page = book_page + i)
            return i, warnings
    warnings.append("Could not auto-detect book-page offset; falling back to 14 (PDF page 15 = book page 1).")
    return 14, warnings


def pdf_index_for_book_page(book_page: int, offset: int) -> int:
    return book_page + offset - 1


def parse_toc(doc, offset: int) -> tuple[list[dict], list[dict], list[str]]:
    """Parse Contents pages for chapters and numbered sections."""
    warnings = []
    raw: list[str] = []
    # Contents occupy printed pages xi–xiii (PDF 11–13) in this NCERT file.
    for i in (10, 11, 12):
        if i < doc.page_count:
            raw.extend(_page_lines(doc[i]))
    if not any(x.lower() == "contents" for x in raw[:8]):
        warnings.append("Expected Contents heading on PDF pages 11-13 was not found.")

    chapters: list[dict] = []
    topics: list[dict] = []
    i = 0
    current_chapter = None

    def _add_chapter(ch_no: int, title: str, start_page: int) -> None:
        nonlocal current_chapter
        existing = next((c for c in chapters if c["chapter_number"] == ch_no), None)
        if existing:
            current_chapter = existing
            return
        current_chapter = {
            "chapter_id": f"ch{ch_no:02d}",
            "chapter_number": ch_no,
            "chapter_name": title,
            "start_page": start_page,
            "end_page": None,
            "topics": [],
            "exercises": [],
        }
        chapters.append(current_chapter)

    def _add_topic(ch_no: int, sec: str, title: str, start_page: int) -> None:
        if current_chapter is None or current_chapter["chapter_number"] != ch_no:
            return
        tid = f"ch{ch_no:02d}_s{sec}"
        if any(t["topic_id"] == tid for t in topics):
            return
        topic = {
            "topic_id": f"ch{ch_no:02d}_s{sec}",
            "chapter_id": current_chapter["chapter_id"],
            "section_number": f"{ch_no}.{sec}",
            "topic_name": title,
            "start_page": start_page,
            "end_page": None,
            "source_excerpt": "",
        }
        topics.append(topic)
        current_chapter["topics"].append(topic["topic_id"])

    while i < len(raw):
        line = raw[i]
        if line.lower().startswith("appendix") or line.lower().startswith("answers"):
            break
        # "1." / title / page
        m_ch = re.fullmatch(r"(\d+)\.", line)
        if m_ch and i + 2 < len(raw) and re.fullmatch(r"\d+", raw[i + 2]):
            title = raw[i + 1]
            if not re.match(r"^\d+\.\d+", title):
                _add_chapter(int(m_ch.group(1)), title, int(raw[i + 2]))
                i += 3
                continue
        # "10. Circles" / page
        m_ch2 = re.fullmatch(r"(\d+)\.\s+(.+)", line)
        if m_ch2 and i + 1 < len(raw) and re.fullmatch(r"\d+", raw[i + 1]):
            _add_chapter(int(m_ch2.group(1)), m_ch2.group(2).strip(), int(raw[i + 1]))
            i += 2
            continue
        # "1.1" / title / page
        m_sec = re.fullmatch(r"(\d+)\.(\d+)", line)
        if m_sec and i + 2 < len(raw) and re.fullmatch(r"\d+", raw[i + 2]):
            title = raw[i + 1]
            if not re.match(r"^\d+\.\d+", title):
                _add_topic(int(m_sec.group(1)), m_sec.group(2), title, int(raw[i + 2]))
                i += 3
                continue
        # "10.1 Introduction" / page
        m_sec2 = re.fullmatch(r"(\d+)\.(\d+)\s+(.+)", line)
        if m_sec2 and i + 1 < len(raw) and re.fullmatch(r"\d+", raw[i + 1]):
            _add_topic(int(m_sec2.group(1)), m_sec2.group(2), m_sec2.group(3).strip(), int(raw[i + 1]))
            i += 2
            continue
        i += 1

    if not chapters:
        warnings.append("TOC parse produced zero chapters; using fallback chapter list.")
        chapters, topics = _fallback_chapters()

    chapters.sort(key=lambda c: c["chapter_number"])
    for idx, ch in enumerate(chapters):
        if idx + 1 < len(chapters):
            ch["end_page"] = chapters[idx + 1]["start_page"] - 1
        else:
            ch["end_page"] = 217  # last numbered chapter before appendix in this book
    ch_by_id = {c["chapter_id"]: c for c in chapters}
    for t in topics:
        ch = ch_by_id.get(t["chapter_id"])
        if ch:
            t["_ch_end"] = ch["end_page"]
    topics.sort(key=lambda t: (t["chapter_id"], t["start_page"], t["section_number"]))
    for idx, t in enumerate(topics):
        same = [x for x in topics if x["chapter_id"] == t["chapter_id"]]
        pos = same.index(t)
        if pos + 1 < len(same):
            t["end_page"] = max(t["start_page"], same[pos + 1]["start_page"] - 1)
        else:
            t["end_page"] = ch_by_id[t["chapter_id"]]["end_page"]
        t.pop("_ch_end", None)

    return chapters, topics, warnings


def _fallback_chapters() -> tuple[list[dict], list[dict]]:
    names = [
        (1, "Real Numbers", 1, 9),
        (2, "Polynomials", 10, 23),
        (3, "Pair of Linear Equations in Two Variables", 24, 37),
        (4, "Quadratic Equations", 38, 47),
        (5, "Arithmetic Progressions", 49, 72),
        (6, "Triangles", 73, 97),
        (7, "Coordinate Geometry", 99, 112),
        (8, "Introduction to Trigonometry", 113, 132),
        (9, "Some Applications of Trigonometry", 133, 143),
        (10, "Circles", 144, 153),
        (11, "Areas Related to Circles", 154, 160),
        (12, "Surface Areas and Volumes", 161, 170),
        (13, "Statistics", 171, 200),
        (14, "Probability", 202, 217),
    ]
    chapters = []
    topics = []
    for n, name, a, b in names:
        cid = f"ch{n:02d}"
        chapters.append(
            {
                "chapter_id": cid,
                "chapter_number": n,
                "chapter_name": name,
                "start_page": a,
                "end_page": b,
                "topics": [],
                "exercises": [],
            }
        )
    return chapters, topics


def chapter_page_text(doc, chapter: dict, offset: int) -> list[tuple[int, int, str]]:
    """Return (pdf_index, book_page, text) for chapter pages."""
    out = []
    for bp in range(chapter["start_page"], chapter["end_page"] + 1):
        idx = pdf_index_for_book_page(bp, offset)
        if 0 <= idx < doc.page_count:
            out.append((idx, bp, doc[idx].get_text("text") or ""))
    return out


def extract_topic_excerpts(doc, topics: list[dict], offset: int, max_chars: int = 1800) -> None:
    for t in topics:
        chunks = []
        for bp in range(t["start_page"], min(t["end_page"], t["start_page"] + 3) + 1):
            idx = pdf_index_for_book_page(bp, offset)
            if 0 <= idx < doc.page_count:
                lines = [_clean_line(x) for x in (doc[idx].get_text("text") or "").splitlines()]
                keep = [ln for ln in lines if ln and not _is_noise(ln) and not CHAPTER_TITLE_RE.match(ln)]
                chunks.append(" ".join(keep))
        excerpt = " ".join(chunks)
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        t["source_excerpt"] = excerpt[:max_chars]


def _split_exercises(full_text: str) -> list[dict]:
    hits = list(EXERCISE_RE.finditer(full_text))
    blocks = []
    for i, m in enumerate(hits):
        start = m.start()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(full_text)
        optional = bool(m.group(3) or "optional" in m.group(0).lower())
        body = full_text[m.end() : end]
        # cut at next numbered section header like 1.3 or Summary of this chapter
        cut = re.search(r"\n\s*\d+\.\d+\s+[A-Z]", body)
        if cut:
            body = body[: cut.start()]
        cut2 = re.search(r"\n\s*\d+\.\d+\s+Summary", body)
        if cut2:
            body = body[: cut2.start()]
        blocks.append(
            {
                "exercise_number": f"{m.group(1)}.{m.group(2)}",
                "chapter_number": int(m.group(1)),
                "optional": optional,
                "raw": body,
                "header": m.group(0),
            }
        )
    return blocks


_ROMAN_SUB = re.compile(
    r"\((i{1,3}|iv|vi{0,3}|v|ix|x{1,2}|xi{0,3})\)",
    re.IGNORECASE,
)
_NARRATIVE_PREFIXES = (
    "the method used",
    "this method",
    "you have seen",
    "we have already",
    "note that",
    "remark :",
)


def _looks_like_question(text: str) -> bool:
    t = text.lower().lstrip()
    if any(t.startswith(p) for p in _NARRATIVE_PREFIXES):
        return False
    return True


def _split_subparts(qno: str, text: str) -> list[tuple[str, str]]:
    hits = list(_ROMAN_SUB.finditer(text))
    if len(hits) < 2:
        return [(qno, text)]
    stem = text[: hits[0].start()].strip()
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        chunk = text[m.start() : end].strip()
        sub_id = m.group(1).lower()
        combined = (stem + " " + chunk).strip() if stem else chunk
        if len(combined) >= 8:
            out.append((f"{qno}{sub_id}", combined))
    return out or [(qno, text)]


def _questions_from_exercise(body: str) -> list[dict]:
    lines = [_clean_line(x) for x in body.splitlines() if _clean_line(x)]
    kept = []
    for ln in lines:
        if _is_noise(ln):
            continue
        if CHAPTER_TITLE_RE.match(ln):
            continue
        kept.append(ln)
    text = "\n".join(kept)
    parts: list[tuple[str, str, bool]] = []
    current_no = None
    current_lines: list[str] = []
    starred = False
    for ln in kept:
        m = QUESTION_START_RE.match(ln)
        if m and int(m.group(1)) <= 40:
            if current_no is not None:
                parts.append((current_no, " ".join(current_lines).strip(), starred))
            current_no = m.group(1)
            rest = m.group(2)
            starred = rest.startswith("*") or ln.startswith("*")
            current_lines = [rest.lstrip("* ").strip() if starred else rest]
        else:
            if current_no is None:
                continue
            if ln.startswith("*") and len(current_lines) == 0:
                starred = True
            current_lines.append(ln.lstrip("* ").strip() if ln.startswith("*") else ln)
    if current_no is not None:
        parts.append((current_no, " ".join(current_lines).strip(), starred))

    questions = []
    for qno, qtext, star in parts:
        qtext = re.sub(r"\s+", " ", qtext).strip()
        if len(qtext) < 8:
            continue
        if not _looks_like_question(qtext):
            continue
        for qn, qt in _split_subparts(qno, qtext):
            questions.append(
                {
                    "question_number": qn,
                    "question_text": qt,
                    "starred": star,
                }
            )
    return questions


def _confidence(text: str) -> str:
    if len(text) < 20:
        return "low"
    weird = text.count("�") + len(re.findall(r"[^\x00-\x7F\u2000-\u206F ]", text))
    # math pdfs have many unicode operators; that is ok
    if len(text) > 40 and "  " not in text[:20]:
        return "high"
    if len(text) >= 20:
        return "medium"
    return "low"


def _topic_ids_for_page(topics: list[dict], chapter_id: str, book_page: int) -> list[str]:
    ch_topics = [t for t in topics if t["chapter_id"] == chapter_id]
    hits = [t for t in ch_topics if t["start_page"] <= book_page <= t["end_page"]]
    nonsum = [t for t in hits if t["topic_name"].lower() != "summary"]
    if nonsum:
        return [nonsum[-1]["topic_id"]]
    prev = [t for t in ch_topics if t["start_page"] <= book_page and t["topic_name"].lower() != "summary"]
    if prev:
        return [prev[-1]["topic_id"]]
    if ch_topics:
        return [ch_topics[0]["topic_id"]]
    return []


def _find_exercise_page(pages: list[tuple[int, int, str]], exercise_number: str) -> int | None:
    pat = re.compile(rf"EXERCISE\s+{re.escape(exercise_number)}", re.I)
    for _, bp, text in pages:
        if pat.search(text):
            return bp
    return None


def import_book(force: bool = False) -> dict:
    out_dir = book_data_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    book_json = out_dir / "book.json"
    if book_json.exists() and not force:
        log.info("Book index already exists at %s (use force=True to reimport).", book_json)
        return json.loads(book_json.read_text(encoding="utf-8"))

    pdf_path = source_path("book_pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(f"Book PDF not found: {pdf_path}")

    log.info("Importing book from %s", pdf_path)
    doc = fitz.open(pdf_path)
    offset, warnings = detect_page_offset(doc)
    log.info("Detected book-page offset=%s (pdf_index = book_page + %s - 1)", offset, offset)

    chapters, topics, toc_warnings = parse_toc(doc, offset)
    warnings.extend(toc_warnings)
    log.info("TOC chapters=%s topics=%s", len(chapters), len(topics))

    extract_topic_excerpts(doc, topics, offset)

    questions: list[dict] = []
    exercises_meta: list[dict] = []
    q_seq = 0

    for ch in chapters:
        pages = chapter_page_text(doc, ch, offset)
        full = "\n".join(t for _, _, t in pages)
        blocks = _split_exercises(full)
        ch_ex_ids = []
        seen_ex = set()
        for block in blocks:
            if block["chapter_number"] != ch["chapter_number"]:
                continue
            if block["exercise_number"] in seen_ex:
                continue
            seen_ex.add(block["exercise_number"])
            ex_id = f"{ch['chapter_id']}_ex{block['exercise_number'].replace('.', '_')}"
            src_page = _find_exercise_page(pages, block["exercise_number"]) or ch["start_page"]
            optional = block["optional"]
            qs = _questions_from_exercise(block["raw"])
            ch_ex_ids.append(ex_id)
            exercises_meta.append(
                {
                    "exercise_id": ex_id,
                    "chapter_id": ch["chapter_id"],
                    "exercise_number": block["exercise_number"],
                    "source_page": src_page,
                    "optional": optional,
                    "question_count": len(qs),
                    "examinable": not optional,
                }
            )
            for q in qs:
                q_seq += 1
                examinable = (not optional) and (not q["starred"])
                reason = []
                if optional:
                    reason.append("optional_exercise")
                if q["starred"]:
                    reason.append("starred_not_from_examination_point_of_view")
                topic_ids = _topic_ids_for_page(topics, ch["chapter_id"], src_page)
                qid = f"bq_{ch['chapter_id']}_{block['exercise_number'].replace('.', '_')}_{q['question_number']}"
                questions.append(
                    {
                        "question_id": qid,
                        "chapter_id": ch["chapter_id"],
                        "topic_ids": topic_ids,
                        "exercise_id": ex_id,
                        "exercise_number": block["exercise_number"],
                        "question_number": q["question_number"],
                        "question_text": q["question_text"],
                        "source_page": src_page,
                        "source_type": "book",
                        "examinable": examinable,
                        "examinable_reason": ",".join(reason) if reason else "exercise_item",
                        "extraction_confidence": _confidence(q["question_text"]),
                    }
                )
        ch["exercises"] = ch_ex_ids

    # Appendices are not examinable chapters. Do not add them to chapters.json as examinable.
    book_cfg_path = source_path("book_configuration")
    language_declared = "hi"
    language_actual = "en"
    if book_cfg_path.exists():
        cfg_txt = book_cfg_path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"Language:\s*Hindi", cfg_txt, re.I):
            language_declared = "hi"

    status = "READY"
    if any("zero chapters" in w.lower() for w in warnings):
        status = "WARN"
    if language_declared != language_actual:
        status = "WARN"
        warnings.append(
            "Book configuration language is Hindi but the PDF body is English NCERT Class X."
        )

    book = {
        "book_id": BOOK_ID,
        "title": "Mathematics, Textbook for Class X (NCERT, Reprint 2026-27)",
        "grade": 10,
        "subject": "Mathematics",
        "language": language_actual,
        "language_declared_in_config": language_declared,
        "source_pdf": str(pdf_path),
        "pdf_page_count": doc.page_count,
        "book_page_offset": offset,
        "chapters": [c["chapter_id"] for c in chapters],
        "status": status,
        "warnings": warnings,
        "counts": {
            "chapters": len(chapters),
            "topics": len(topics),
            "exercises": len(exercises_meta),
            "book_questions": len(questions),
            "examinable_questions": sum(1 for q in questions if q["examinable"]),
        },
    }

    _write_json(out_dir / "book.json", book)
    _write_json(out_dir / "chapters.json", {"chapters": chapters, "exercises": exercises_meta})
    _write_json(out_dir / "topics.json", {"topics": topics})
    _write_json(out_dir / "book_questions.json", {"questions": questions})

    log.info(
        "Book import complete: chapters=%s topics=%s questions=%s examinable=%s status=%s",
        book["counts"]["chapters"],
        book["counts"]["topics"],
        book["counts"]["book_questions"],
        book["counts"]["examinable_questions"],
        status,
    )
    doc.close()
    return book


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_book_index() -> dict:
    d = book_data_dir()
    book = json.loads((d / "book.json").read_text(encoding="utf-8"))
    chapters = json.loads((d / "chapters.json").read_text(encoding="utf-8"))
    topics = json.loads((d / "topics.json").read_text(encoding="utf-8"))
    questions = json.loads((d / "book_questions.json").read_text(encoding="utf-8"))
    return {
        "book": book,
        "chapters": chapters["chapters"],
        "exercises": chapters.get("exercises", []),
        "topics": topics["topics"],
        "questions": questions["questions"],
    }


if __name__ == "__main__":
    import_book(force=True)
