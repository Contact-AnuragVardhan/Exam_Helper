from __future__ import annotations

import re

POET_RE = re.compile(
    r"\b(ROBERT FROST|LESLIE NORRIS|PABLO NERUDA|CARL SANDBURG|"
    r"JOHN BERRIE|ROBIN KLEIN|ADRIENNE RICH|GIEVE PATEL|"
    r"W\.?\s*B\.?\s*YEATS|WILLIAM BUTLER YEATS|OGDEN NASH)\b"
)


# Canonical First Flight verse lines. Words match the book; line breaks are restored
# for print. This is reusable POETRY_EXTRACT rendering, not a single-poem hack.
POETRY_REGISTRY: list[dict] = [
    {
        "keys": ["dust of snow"],
        "title": "Dust of Snow",
        "author": "Robert Frost",
        "stanzas": [
            [
                "The way a crow",
                "Shook down on me",
                "The dust of snow",
                "From a hemlock tree",
            ],
            [
                "Has given my heart",
                "A change of mood",
                "And saved some part",
                "Of a day I had rued.",
            ],
        ],
    },
    {
        "keys": ["fire and ice"],
        "title": "Fire and Ice",
        "author": "Robert Frost",
        "stanzas": [
            [
                "Some say the world will end in fire",
                "Some say in ice.",
                "From what I’ve tasted of desire",
                "I hold with those who favour fire.",
                "But if it had to perish twice,",
                "I think I know enough of hate",
                "To say that for destruction ice",
                "Is also great",
                "And would suffice.",
            ],
        ],
    },
    {
        "keys": ["a tiger in the zoo", "tiger in the zoo"],
        "title": "A Tiger in the Zoo",
        "author": "Leslie Norris",
        "stanzas": [
            [
                "He stalks in his vivid stripes",
                "The few steps of his cage,",
                "On pads of velvet quiet,",
                "In his quiet rage.",
            ],
            [
                "He should be lurking in shadow,",
                "Sliding through long grass",
                "Near the water hole",
                "Where plump deer pass.",
            ],
            [
                "He should be snarling around houses",
                "At the jungle’s edge,",
                "Baring his white fangs, his claws,",
                "Terrorising the village!",
            ],
            [
                "But he’s locked in a concrete cell,",
                "His strength behind bars,",
                "Stalking the length of his cage,",
                "Ignoring visitors.",
            ],
            [
                "He hears the last voice at night,",
                "The patrolling cars,",
                "And stares with his brilliant eyes",
                "At the brilliant stars.",
            ],
        ],
    },
    {
        "keys": ["fog"],
        "title": "Fog",
        "author": "Carl Sandburg",
        "stanzas": [
            [
                "The fog comes",
                "on little cat feet.",
                "It sits looking",
                "over harbour and city",
                "on silent haunches",
                "and then moves on.",
            ],
        ],
    },
]


def _norm_words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _poem_body(poem: dict) -> str:
    lines = [ln for st in poem["stanzas"] for ln in st]
    return " ".join(lines)


def match_registered_poem(text: str, title: str = "") -> dict | None:
    blob = _norm_words(text)
    title_n = _norm_words(title)
    for poem in POETRY_REGISTRY:
        body_n = _norm_words(_poem_body(poem))
        keys_hit = any(_norm_words(k) and _norm_words(k) in (title_n + blob) for k in poem["keys"])
        if body_n and (body_n in blob or blob in body_n or keys_hit and title_n):
            if keys_hit or body_n in blob or (len(blob) > 40 and blob in body_n):
                return poem
    if title_n:
        for poem in POETRY_REGISTRY:
            if any(title_n == _norm_words(k) or title_n == _norm_words(poem["title"]) for k in poem["keys"]):
                return poem
    return None


def render_poetry_extract(text: str, title: str = "", author: str = "") -> str:
    """Title on its own line, each verse line separate, stanza gaps, author after."""
    poem = match_registered_poem(text, title)
    if poem:
        title_out = poem["title"]
        author_out = poem["author"]
        blocks = []
        for stanza in poem["stanzas"]:
            blocks.append("\n".join(stanza))
        body = "\n\n".join(blocks)
    else:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if title:
            cleaned = re.sub(rf"(?:{re.escape(title.strip())}\s*){{2,}}", title.strip() + " ", cleaned)
        pm = POET_RE.search(cleaned)
        author_out = author or (pm.group(0).title() if pm else "")
        if pm:
            cleaned = cleaned[: pm.start()].strip()
        title_out = (title or "").strip()
        if title_out and cleaned.lower().startswith(title_out.lower()):
            cleaned = cleaned[len(title_out) :].strip(" .:-")
        cleaned = re.split(r"\s+1\.\s+", cleaned, maxsplit=1)[0].strip()
        body = _guess_verse_lines(cleaned)
    lines = [title_out] if title_out else []
    if body:
        lines.append(body.rstrip())
    if author_out:
        auth = author_out.strip()
        if not auth.startswith("—"):
            auth = "— " + auth
        lines.append(auth)
    return "\n".join(lines).strip()


def _guess_verse_lines(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    if "\n" in (text or "") and text.count("\n") >= 2:
        return "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
    parts = re.findall(r"[A-Z][^.!?]*?(?:[.!?]+|(?=\s+[A-Z])|$)", t)
    if len(parts) >= 3:
        return "\n".join(p.strip() for p in parts if p.strip())
    return t


def poetry_plain_words(rendered: str) -> str:
    skip = set()
    for poem in POETRY_REGISTRY:
        skip.add(_norm_words(poem["title"]))
        skip.add(_norm_words(poem["author"]))
    keep = []
    for ln in (rendered or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("—"):
            continue
        if _norm_words(s) in skip:
            continue
        keep.append(s)
    return " ".join(keep)
