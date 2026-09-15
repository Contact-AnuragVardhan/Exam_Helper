from __future__ import annotations

import re


GREETINGS = frozenset({"hi", "hello", "hey", "start", "menu"})
GLOBAL_MENU = "MENU"
GLOBAL_BACK = "BACK"
GLOBAL_CANCEL = "CANCEL"


def normalize_text(raw: str | None) -> str:
    return (raw or "").replace("\u00a0", " ").strip()


def normalized_command(raw: str | None) -> str:
    return normalize_text(raw).upper()


def is_greeting(raw: str | None) -> bool:
    return normalize_text(raw).lower() in GREETINGS


def is_menu(raw: str | None) -> bool:
    return normalized_command(raw) == GLOBAL_MENU or normalize_text(raw).lower() == "menu"


def is_back(raw: str | None) -> bool:
    return normalized_command(raw) == GLOBAL_BACK


def is_cancel(raw: str | None) -> bool:
    return normalized_command(raw) == GLOBAL_CANCEL


def is_all(raw: str | None) -> bool:
    return normalized_command(raw) == "ALL"


def parse_menu_number(raw: str | None) -> int | None:
    text = normalize_text(raw)
    if not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def parse_index_list(raw: str | None, count: int) -> list[int]:
    """Parse 1,2,4 or ALL. Raises ValueError on empty/malformed/out-of-range input."""
    text = normalize_text(raw)
    if not text:
        raise ValueError("empty")
    if text.upper() == "ALL":
        if count < 1:
            raise ValueError("empty")
        return list(range(1, count + 1))
    nums: list[int] = []
    seen: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if not re.fullmatch(r"\d+", part):
            raise ValueError("malformed")
        n = int(part)
        if n < 1 or n > count:
            raise ValueError("range")
        if n not in seen:
            nums.append(n)
            seen.add(n)
    if not nums:
        raise ValueError("empty")
    return nums
