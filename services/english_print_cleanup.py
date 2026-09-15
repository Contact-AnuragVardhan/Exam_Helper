from __future__ import annotations

import ast
import json
import re


EXTRACT_FORMATS = {"LITERATURE_EXTRACT_MCQ"}
READING_FORMATS = {"UNSEEN_PASSAGE_MCQ", "NOTE_MAKING"}
MCQ_FORMATS = {"UNSEEN_PASSAGE_MCQ", "LITERATURE_MCQ"}

FURNITURE_RE = re.compile(
    r"\b("
    r"BEFORE YOU READ|TO THE TEACHER|Oral Comprehension Check|"
    r"Thinking about the (?:Text|Poem|Language)|"
    r"What we have done|What you can do|IN THIS LESSON|"
    r"Fill out the Money Order form"
    r")\b",
    re.I,
)

POET_RE = re.compile(
    r"\b(ROBERT FROST|LESLIE NORRIS|PABLO NERUDA|CARL SANDBURG|"
    r"JOHN BERRIE|ROBIN KLEIN|ADRIENNE RICH|GIEVE PATEL|"
    r"W\.?\s*B\.?\s*YEATS|WILLIAM BUTLER YEATS)\b"
)

STORY_START_RE = re.compile(
    r"(?:THE house\b|TENTH May\b|THE young seagull\b|I His First Flight\b|"
    r"The Black Aeroplane\b|The way a crow\b|Some say the world will end\b|"
    r"He stalks in his vivid stripes\b)",
    re.I,
)

OPTION_LINE_RE = re.compile(
    r"^\(?([A-Da-d])\)?[).]\s*(.*)$"
)
ALREADY_LETTER_RE = re.compile(r"^[A-D]\)\s+\S")
ALREADY_PAREN_RE = re.compile(r"^\([A-Da-d]\)\s+\S")


def options_blob(options) -> str:
    parts = []
    for o in options or []:
        if isinstance(o, dict):
            parts.append(str(o.get("text") or o.get("label") or ""))
        else:
            parts.append(str(o))
    return " ".join(parts)


def try_parse_mapping(text: str) -> dict | None:
    s = (text or "").strip()
    if not s or s[0] != "{":
        return None
    try:
        obj = ast.literal_eval(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return None


def parse_option(opt) -> tuple[str, str]:
    if opt is None:
        return "", ""
    if isinstance(opt, dict):
        lab = str(opt.get("label") or opt.get("key") or "").strip()
        text = str(opt.get("text") or opt.get("value") or "").strip()
        return lab, text
    s = str(opt).strip()
    mapped = try_parse_mapping(s)
    if mapped is not None:
        return parse_option(mapped)
    m = OPTION_LINE_RE.match(s)
    if m:
        return m.group(1), (m.group(2) or "").strip()
    return "", s


def normalize_options(options) -> list[dict]:
    if options is None:
        return []
    if isinstance(options, dict):
        options = [options]
    if not isinstance(options, list):
        mapped = try_parse_mapping(str(options))
        options = [mapped] if mapped else [options]
    out = []
    letters = "ABCD"
    for i, raw in enumerate(options):
        lab, text = parse_option(raw)
        lab = lab.strip("(). ").upper()
        if lab in ("A", "B", "C", "D") and len(lab) == 1:
            pass
        elif not lab:
            lab = letters[i] if i < 4 else str(i + 1)
        else:
            lab = lab[:1].upper() if lab[:1].isalpha() else (letters[i] if i < 4 else str(i + 1))
        if text:
            out.append({"label": lab, "text": text})
    return out


def format_option_line(opt, *, letter_style: bool = False) -> str:
    """Math keeps existing '(a) text' strings. English MCQs print 'A) text'."""
    if isinstance(opt, str):
        s = opt.strip()
        if not letter_style and (ALREADY_PAREN_RE.match(s) or OPTION_LINE_RE.match(s)):
            if try_parse_mapping(s) is None:
                return s
        if letter_style and ALREADY_LETTER_RE.match(s) and try_parse_mapping(s) is None:
            return s
    lab, text = parse_option(opt)
    lab = lab.strip("(). ")
    if not lab:
        return text
    if letter_style:
        return f"{lab.upper()}) {text}".strip()
    if not lab.startswith("("):
        lab = f"({lab})"
    return f"{lab} {text}".strip()


def collapse_repeated_runs(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    t = re.sub(r"\b((?:[A-Z][A-Za-z']+\s+){0,3}[A-Z][A-Za-z']+)(?:\s+\1){1,}\b", r"\1", t)
    t = re.sub(r"\b(\S{4,})(?:\s+\1){2,}\b", r"\1", t)
    return t.strip()


def collapse_title_repeats(text: str, title: str | None = None) -> str:
    t = collapse_repeated_runs(text)
    if title:
        esc = re.escape(title.strip())
        t = re.sub(rf"(?:{esc}\s*){{2,}}", title.strip() + " ", t)
        words = title.strip().split()
        if len(words) >= 2:
            trunc = re.escape(" ".join(words[:-1]) + " " + words[-1][:3])
            t = re.sub(rf"(?:{trunc}\w*\s*){{2,}}", title.strip() + " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def looks_like_retrieval_dump(text: str) -> bool:
    t = text or ""
    if not t.strip():
        return False
    low = t.lower()
    if "before you read" in low or "to the teacher" in low:
        return True
    if "fill out the money order" in low:
        return True
    if "reprint 2026" in low:
        return True
    if low.count("fire and ice") >= 3:
        return True
    if "dust of sno" in low and low.count("dust of sno") >= 2:
        return True
    if FURNITURE_RE.search(t) and len(t) > 240:
        return True
    if len(t) > 750 and re.search(r"\b(Lencho|young seagull|Mandela|hemlock tree)\b", t) and t.count("?") == 0:
        return True
    if len(t) > 900 and POET_RE.search(t) and re.search(r"\s1\.\s+", t):
        return True
    return False


def strip_book_furniture(text: str, title: str | None = None) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    t = re.sub(r"REPRINT 2026-27", " ", t, flags=re.I)
    t = re.split(
        r"\b(?:Oral Comprehension Check|Thinking about the Text|Thinking about the Poem|"
        r"Thinking about Language|What we have done|What you can do)\b",
        t,
        maxsplit=1,
        flags=re.I,
    )[0]
    m = re.search(r"BEFORE YOU READ", t, flags=re.I)
    if m:
        after = t[m.start():]
        sm = STORY_START_RE.search(after)
        if sm:
            t = (t[: m.start()] + " " + after[sm.start():]).strip()
        elif title and title.lower() in after.lower():
            idx = after.lower().find(title.lower())
            t = (t[: m.start()] + " " + after[idx:]).strip()
        else:
            t = (t[: m.start()] + " " + after[len("BEFORE YOU READ") :]).strip()
            t = re.sub(r"Activity\s+\d+\..{0,900}", " ", t, count=1)
    t = re.sub(r"\bTO THE TEACHER\b.{0,400}", " ", t, flags=re.I)
    t = collapse_title_repeats(t, title)
    return t.strip()


def literary_excerpt(raw: str, unit_name: str, kind: str) -> str:
    t = strip_book_furniture(raw or "", unit_name)
    if (kind or "").lower() == "poem":
        pm = POET_RE.search(t)
        if pm:
            t = t[: pm.end()]
        else:
            t = re.split(r"\s+1\.\s+", t, maxsplit=1)[0]
    else:
        t = re.split(r"\s+1\.\s+(?:Who|What|Why|How|Where|When|Which|Did|Do |Does)", t, maxsplit=1)[0]
    t = collapse_title_repeats(t, unit_name)
    return t.strip()[:4000]


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z']*", text or ""))


def short_extract(text: str, kind: str = "", title: str = "", max_chars: int = 420) -> str:
    t = literary_excerpt(text or "", title, kind)
    if not t:
        t = strip_book_furniture(text or "", title)
    if not t:
        return ""
    if (kind or "").lower() == "poem":
        pm = POET_RE.search(t)
        if pm:
            t = t[: pm.end()]
        if len(t) > max_chars + 80:
            t = t[:max_chars].rsplit(" ", 1)[0] + "…"
        return t.strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    keep = []
    for s in sentences:
        if FURNITURE_RE.search(s) or looks_like_retrieval_dump(s):
            continue
        if re.match(r"^(Activity|BEFORE YOU READ)\b", s, re.I):
            continue
        keep.append(s)
        joined = " ".join(keep)
        if len(joined) >= 220 or len(keep) >= 3:
            break
    joined = " ".join(keep) if keep else t[:max_chars]
    if len(joined) > max_chars:
        joined = joined[:max_chars].rsplit(" ", 1)[0] + "…"
    return joined.strip()


def clean_question_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    mapped = try_parse_mapping(t)
    if mapped:
        for k in ("stem", "question_text", "text", "question"):
            if mapped.get(k):
                t = str(mapped[k]).strip()
                break
        else:
            t = ""
    if looks_like_retrieval_dump(t) or FURNITURE_RE.search(t):
        t = strip_book_furniture(t)
        t = re.sub(r"^(?:BEFORE YOU READ|TO THE TEACHER)\b[:.\s]*", "", t, flags=re.I)
    t = collapse_repeated_runs(t)
    return t.strip()


def printable_passage(item: dict) -> str:
    fmt = item.get("format_id") or ""
    title = item.get("chapter_or_poem") or ""
    kind = (item.get("kind") or "").lower()
    extract = (item.get("extract") or "").strip()
    passage = (item.get("passage") or "").strip()
    if fmt in EXTRACT_FORMATS:
        return exam_extract_text(item)
    if fmt in READING_FORMATS:
        if looks_like_retrieval_dump(passage):
            return ""
        return collapse_repeated_runs(passage)
    return ""


def exam_extract_text(item: dict) -> str:
    title = item.get("chapter_or_poem") or ""
    kind = (item.get("kind") or "").lower()
    extract = (item.get("extract") or "").strip()
    passage = (item.get("passage") or "").strip()
    context = (item.get("source_context") or item.get("excerpt") or "").strip()
    raw = extract or passage or context
    if kind == "poem" or "\n" in raw:
        from .english_poetry_extract import render_poetry_extract

        return render_poetry_extract(raw, title)
    if 110 <= _word_count(raw) <= 200 and not looks_like_retrieval_dump(raw) and not FURNITURE_RE.search(raw):
        return raw
    from .english_content_quality import longer_book_prose_extract

    return longer_book_prose_extract(context or raw, title)


def sanitize_item(item: dict) -> dict:
    rec = dict(item)
    fmt = rec.get("format_id") or ""
    title = rec.get("chapter_or_poem") or ""
    kind = rec.get("kind") or ""
    rec["question_text"] = clean_question_text(rec.get("question_text") or "")
    rec["choice_b"] = clean_question_text(rec.get("choice_b") or "")
    rec["options"] = normalize_options(rec.get("options") or [])
    context = rec.get("source_context") or rec.get("excerpt") or ""
    if looks_like_retrieval_dump(rec["question_text"]):
        rec["question_text"] = clean_question_text(rec["question_text"])
    if fmt in EXTRACT_FORMATS:
        rec["extract"] = exam_extract_text(rec)
        rec["passage"] = rec["extract"]
    elif fmt in READING_FORMATS:
        p = rec.get("passage") or ""
        rec["passage"] = "" if looks_like_retrieval_dump(p) else collapse_repeated_runs(p)
        rec["extract"] = ""
    else:
        rec["passage"] = ""
        rec["extract"] = ""
    return rec
