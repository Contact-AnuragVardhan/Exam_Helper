from __future__ import annotations

import re
from pathlib import Path

from .logger import get_logger
from .paths import source_path


log = get_logger("english_syllabus")

BOOK_ALIASES = {
    "first flight": "First Flight",
    "book first flight": "First Flight",
    "footprints without feet": "Footprints Without Feet",
    "book 2 footprints without feet": "Footprints Without Feet",
    "footprints": "Footprints Without Feet",
}

IMPORTED_BOOKS = {
    "First Flight": "english_book_pdf",
}

FORBIDDEN_UNLESS_SYLLABUS = [
    "a tiger in the zoo",
    "tiger in the zoo",
    "a triumph of surgery",
    "triumph of surgery",
    "tricki",
    "mrs pumphrey",
    "mrs. pumphrey",
    "footprints without feet",
]


def _norm(name: str) -> str:
    t = (name or "").lower()
    t = t.replace("poem study:", " ")
    t = t.replace("ch.", " ")
    t = t.replace("chapter", " ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("fr eedom", "freedom")
    return t


def _clean_item(name: str) -> str:
    n = (name or "").strip()
    n = re.sub(r"^(Poem Study:\s*)", "", n, flags=re.I)
    n = re.sub(r"^(Ch\.?\s*\d+\s*:\s*)", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" -:\t")
    if _norm(n) in ("nelson mandela",):
        return "Nelson Mandela: Long Walk to Freedom"
    if _norm(n) in ("two stories about flying", "two stories about flying".replace("flying", "flying")):
        return "Two Stories about Flying"
    if _norm(n) == "a letter to god":
        return "A Letter to God"
    if _norm(n) == "dust of snow":
        return "Dust of Snow"
    if _norm(n) == "fire and ice":
        return "Fire and Ice"
    return n


def parse_english_syllabus_text(text: str) -> dict:
    groups: list[dict] = []
    current_book = None
    current_items: list[str] = []
    mode = None
    prose: list[str] = []
    poems: list[str] = []

    def _flush():
        nonlocal current_book, current_items
        if current_book:
            groups.append({"book": current_book, "items": list(current_items)})
        current_book = None
        current_items = []

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        book_m = re.match(r"^book\s+\d*\s*:?\s*(.+)$", line, re.I)
        if book_m or low.startswith("book "):
            _flush()
            rest = book_m.group(1) if book_m else re.sub(r"^book\s+\d*\s*:?\s*", "", line, flags=re.I)
            rest = re.sub(r"\s*-\s*grade\s*\d+\s*$", "", rest, flags=re.I).strip(" -")
            key = _norm(rest)
            current_book = BOOK_ALIASES.get(key, rest.title() if rest else "Unknown book")
            if "first flight" in key:
                current_book = "First Flight"
            elif "footprint" in key:
                current_book = "Footprints Without Feet"
            mode = "items"
            continue
        if re.match(r"^chapters?\s*:?\s*$", line, re.I):
            mode = "prose"
            continue
        if re.match(r"^topics?\s+explicitly\s+selected\s*:?\s*$", line, re.I):
            mode = "poem"
            continue
        if line.endswith(":") and len(line) < 40 and "chapter" not in low:
            continue
        item = _clean_item(line)
        if not item or item.lower() in ("chapters", "topics"):
            continue
        current_items.append(item)
        if mode == "poem" or item.lower() in ("dust of snow", "fire and ice") or "poem" in low:
            poems.append(item)
        else:
            prose.append(item)

    _flush()
    if not groups and (prose or poems):
        groups.append({"book": "First Flight", "items": prose + poems})

    missing = []
    for g in groups:
        book = g["book"]
        key = IMPORTED_BOOKS.get(book)
        if not key:
            missing.append(book)
            continue
        try:
            p = source_path(key)
        except Exception:
            p = Path()
        if not p.exists():
            missing.append(book)

    return {
        "groups": groups,
        "prose": prose,
        "poems": poems,
        "all_items": [i for g in groups for i in g["items"]],
        "missing_books": missing,
    }


def load_active_english_syllabus(exam_config: dict | None = None) -> dict:
    path = None
    if exam_config and exam_config.get("syllabus_file"):
        path = Path(exam_config["syllabus_file"])
    if path is None:
        path = source_path("english_q1_syllabus_txt")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    parsed = parse_english_syllabus_text(text)
    parsed["source_file"] = str(path)
    log.info(
        "English syllabus books=%s items=%s missing=%s",
        [g["book"] for g in parsed["groups"]],
        parsed["all_items"],
        parsed["missing_books"],
    )
    return parsed


def names_match(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    if na.replace("the ", "") == nb.replace("the ", ""):
        return True
    return False


def item_allowed(name: str, syllabus: dict) -> bool:
    return any(names_match(name, x) for x in syllabus.get("all_items") or [])
