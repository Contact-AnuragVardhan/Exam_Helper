from __future__ import annotations

import random
import re
import string

from .models import AllowedContentSet


FILLER_WORDS = {
    "multiply", "expand", "equation", "calculation", "verification", "equality",
    "product", "integers", "polynomial", "quadratic", "compare", "ratio",
    "pair", "comparison", "गुणा", "विस्तार", "समीकरण", "गणना", "सत्यापन",
    "समानता", "गुणनफल", "पूर्णांक", "बहुपद", "द्विघात", "अनुपात", "तुलना",
    "युग्म", "verify", "check", "solve",
}

# Natural one-to-one facts from NCERT Class 10 Maths Ch 1–4.
# Not created by chopping a solve/prove exercise into process-words.
NATURAL_PAIRS = [
    {
        "pair_id": "ch01_hcf_6_20",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 4,
        "source_ref": "Example 2, Section 1.2",
        "a_en": "HCF of 6 and 20",
        "b_en": "2",
        "a_hi": "6 और 20 का HCF",
        "b_hi": "2",
    },
    {
        "pair_id": "ch01_lcm_6_20",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 4,
        "source_ref": "Example 2, Section 1.2",
        "a_en": "LCM of 6 and 20",
        "b_en": "60",
        "a_hi": "6 और 20 का LCM",
        "b_hi": "60",
    },
    {
        "pair_id": "ch01_hcf_6_72_120",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 5,
        "source_ref": "Example 4, Section 1.2",
        "a_en": "HCF of 6, 72 and 120",
        "b_en": "6",
        "a_hi": "6, 72 और 120 का HCF",
        "b_hi": "6",
    },
    {
        "pair_id": "ch01_lcm_6_72_120",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 5,
        "source_ref": "Example 4, Section 1.2",
        "a_en": "LCM of 6, 72 and 120",
        "b_en": "360",
        "a_hi": "6, 72 और 120 का LCM",
        "b_hi": "360",
    },
    {
        "pair_id": "ch01_hcf_lcm_identity",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 4,
        "source_ref": "Section 1.2, after Example 2",
        "a_en": "HCF(a, b) × LCM(a, b)",
        "b_en": "a × b",
        "a_hi": "HCF(a, b) × LCM(a, b)",
        "b_hi": "a × b",
    },
    {
        "pair_id": "ch01_fta",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 3,
        "source_ref": "Theorem 1.1, Section 1.2",
        "a_en": "Fundamental Theorem of Arithmetic",
        "b_en": "unique prime factorisation",
        "a_hi": "अंकगणित की आधारभूत प्रमेय",
        "b_hi": "अद्वितीय अभाज्य गुणनखंडन",
    },
    {
        "pair_id": "ch01_sqrt2",
        "chapter_id": "ch01",
        "topic_id": "ch01_s3",
        "source_page": 7,
        "source_ref": "Theorem 1.3, Section 1.3",
        "a_en": "√2",
        "b_en": "irrational",
        "a_hi": "√2",
        "b_hi": "अपरिमेय",
    },
    {
        "pair_id": "ch01_sqrt9",
        "chapter_id": "ch01",
        "topic_id": "ch01_s3",
        "source_page": 6,
        "source_ref": "Section 1.3 (√9 = 3)",
        "a_en": "√9",
        "b_en": "rational",
        "a_hi": "√9",
        "b_hi": "परिमेय",
    },
    {
        "pair_id": "ch02_deg_linear",
        "chapter_id": "ch02",
        "topic_id": "ch02_s1",
        "source_page": 10,
        "source_ref": "Section 2.1",
        "a_en": "Degree of a linear polynomial",
        "b_en": "1",
        "a_hi": "रैखिक बहुपद की घात",
        "b_hi": "1",
    },
    {
        "pair_id": "ch02_deg_cubic",
        "chapter_id": "ch02",
        "topic_id": "ch02_s1",
        "source_page": 11,
        "source_ref": "Section 2.1",
        "a_en": "Degree of a cubic polynomial",
        "b_en": "3",
        "a_hi": "त्रिघात बहुपद की घात",
        "b_hi": "3",
    },
    {
        "pair_id": "ch02_zero_linear",
        "chapter_id": "ch02",
        "topic_id": "ch02_s1",
        "source_page": 11,
        "source_ref": "Section 2.1",
        "a_en": "Zero of ax + b (a ≠ 0)",
        "b_en": "−b/a",
        "a_hi": "ax + b (a ≠ 0) का शून्यक",
        "b_hi": "−b/a",
    },
    {
        "pair_id": "ch02_product_zeroes",
        "chapter_id": "ch02",
        "topic_id": "ch02_s3",
        "source_page": 20,
        "source_ref": "Section 2.3",
        "a_en": "Product of zeroes of ax² + bx + c",
        "b_en": "c/a",
        "a_hi": "ax² + bx + c के शून्यकों का गुणनफल",
        "b_hi": "c/a",
    },
    {
        "pair_id": "ch02_sum_zeroes",
        "chapter_id": "ch02",
        "topic_id": "ch02_s3",
        "source_page": 20,
        "source_ref": "Section 2.3",
        "a_en": "Sum of zeroes of ax² + bx + c",
        "b_en": "−b/a",
        "a_hi": "ax² + bx + c के शून्यकों का योग",
        "b_hi": "−b/a",
    },
    {
        "pair_id": "ch02_quad_poly_form",
        "chapter_id": "ch02",
        "topic_id": "ch02_s1",
        "source_page": 10,
        "source_ref": "Section 2.1",
        "a_en": "Standard form of a quadratic polynomial",
        "b_en": "ax² + bx + c, a ≠ 0",
        "a_hi": "द्विघात बहुपद का मानक रूप",
        "b_hi": "ax² + bx + c, a ≠ 0",
    },
    {
        "pair_id": "ch02_zeroes_x2_3x_4",
        "chapter_id": "ch02",
        "topic_id": "ch02_s1",
        "source_page": 11,
        "source_ref": "Section 2.1, p(x) = x² − 3x − 4",
        "a_en": "Zeroes of x² − 3x − 4",
        "b_en": "−1 and 4",
        "a_hi": "x² − 3x − 4 के शून्यक",
        "b_hi": "−1 और 4",
    },
    {
        "pair_id": "ch03_unique",
        "chapter_id": "ch03",
        "topic_id": "ch03_s2",
        "source_page": 26,
        "source_ref": "Section 3.2 (intersecting lines)",
        "a_en": "a1/a2 ≠ b1/b2",
        "b_en": "exactly one solution",
        "a_hi": "a1/a2 ≠ b1/b2",
        "b_hi": "एक अद्वितीय हल",
    },
    {
        "pair_id": "ch03_none",
        "chapter_id": "ch03",
        "topic_id": "ch03_s2",
        "source_page": 26,
        "source_ref": "Section 3.2 (parallel lines)",
        "a_en": "a1/a2 = b1/b2 ≠ c1/c2",
        "b_en": "no solution",
        "a_hi": "a1/a2 = b1/b2 ≠ c1/c2",
        "b_hi": "कोई हल नहीं",
    },
    {
        "pair_id": "ch03_infinite",
        "chapter_id": "ch03",
        "topic_id": "ch03_s2",
        "source_page": 26,
        "source_ref": "Section 3.2 (coincident lines)",
        "a_en": "a1/a2 = b1/b2 = c1/c2",
        "b_en": "infinitely many solutions",
        "a_hi": "a1/a2 = b1/b2 = c1/c2",
        "b_hi": "अनंत हल",
    },
    {
        "pair_id": "ch03_consistent",
        "chapter_id": "ch03",
        "topic_id": "ch03_s2",
        "source_page": 26,
        "source_ref": "Section 3.2",
        "a_en": "Consistent pair of linear equations",
        "b_en": "at least one solution",
        "a_hi": "रैखिक समीकरणों का संगत युग्म",
        "b_hi": "कम से कम एक हल",
    },
    {
        "pair_id": "ch03_inconsistent",
        "chapter_id": "ch03",
        "topic_id": "ch03_s2",
        "source_page": 26,
        "source_ref": "Section 3.2",
        "a_en": "Inconsistent pair of linear equations",
        "b_en": "no solution",
        "a_hi": "रैखिक समीकरणों का असंगत युग्म",
        "b_hi": "कोई हल नहीं",
    },
    {
        "pair_id": "ch04_std_form",
        "chapter_id": "ch04",
        "topic_id": "ch04_s2",
        "source_page": 39,
        "source_ref": "Section 4.2",
        "a_en": "Standard form of a quadratic equation",
        "b_en": "ax² + bx + c = 0, a ≠ 0",
        "a_hi": "द्विघात समीकरण का मानक रूप",
        "b_hi": "ax² + bx + c = 0, a ≠ 0",
    },
    {
        "pair_id": "ch04_disc",
        "chapter_id": "ch04",
        "topic_id": "ch04_s4",
        "source_page": 44,
        "source_ref": "Section 4.4",
        "a_en": "Discriminant of ax² + bx + c = 0",
        "b_en": "b² − 4ac",
        "a_hi": "ax² + bx + c = 0 का विविक्तकर",
        "b_hi": "b² − 4ac",
    },
    {
        "pair_id": "ch04_d_pos",
        "chapter_id": "ch04",
        "topic_id": "ch04_s4",
        "source_page": 44,
        "source_ref": "Section 4.4",
        "a_en": "D > 0",
        "b_en": "two distinct real roots",
        "a_hi": "D > 0",
        "b_hi": "दो भिन्न वास्तविक मूल",
    },
    {
        "pair_id": "ch04_d_zero",
        "chapter_id": "ch04",
        "topic_id": "ch04_s4",
        "source_page": 44,
        "source_ref": "Section 4.4",
        "a_en": "D = 0",
        "b_en": "two equal real roots",
        "a_hi": "D = 0",
        "b_hi": "दो समान वास्तविक मूल",
    },
    {
        "pair_id": "ch04_d_neg",
        "chapter_id": "ch04",
        "topic_id": "ch04_s4",
        "source_page": 44,
        "source_ref": "Section 4.4",
        "a_en": "D < 0",
        "b_en": "no real roots",
        "a_hi": "D < 0",
        "b_hi": "कोई वास्तविक मूल नहीं",
    },
    {
        "pair_id": "ch02_deg_quadratic",
        "chapter_id": "ch02",
        "topic_id": "ch02_s1",
        "source_page": 10,
        "source_ref": "Section 2.1",
        "a_en": "Degree of a quadratic polynomial",
        "b_en": "2",
        "a_hi": "द्विघात बहुपद की घात",
        "b_hi": "2",
    },
    {
        "pair_id": "ch01_4n",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 4,
        "source_ref": "Example 1, Section 1.2",
        "a_en": "4ⁿ for a natural number n",
        "b_en": "never ends with digit 0",
        "a_hi": "प्राकृत संख्या n के लिए 4ⁿ",
        "b_hi": "कभी अंक 0 पर समाप्त नहीं होता",
    },
    {
        "pair_id": "ch04_factor_method",
        "chapter_id": "ch04",
        "topic_id": "ch04_s3",
        "source_page": 42,
        "source_ref": "Section 4.3",
        "a_en": "Solving ax² + bx + c = 0 by factorisation",
        "b_en": "write as a product of linear factors",
        "a_hi": "ax² + bx + c = 0 को गुणनखंड विधि से हल करना",
        "b_hi": "रैखिक गुणनखंडों के गुणनफल के रूप में लिखना",
    },
    {
        "pair_id": "ch01_hcf_96_404",
        "chapter_id": "ch01",
        "topic_id": "ch01_s2",
        "source_page": 5,
        "source_ref": "Example 3, Section 1.2",
        "a_en": "HCF of 96 and 404",
        "b_en": "4",
        "a_hi": "96 और 404 का HCF",
        "b_hi": "4",
    },
    {
        "pair_id": "ch01_3sqrt2",
        "chapter_id": "ch01",
        "topic_id": "ch01_s3",
        "source_page": 8,
        "source_ref": "Example 7, Section 1.3",
        "a_en": "3√2",
        "b_en": "irrational",
        "a_hi": "3√2",
        "b_hi": "अपरिमेय",
    },
    {
        "pair_id": "ch02_linear_graph",
        "chapter_id": "ch02",
        "topic_id": "ch02_s2",
        "source_page": 12,
        "source_ref": "Section 2.2",
        "a_en": "Graph of y = ax + b, a ≠ 0",
        "b_en": "a straight line",
        "a_hi": "y = ax + b, a ≠ 0 का ग्राफ",
        "b_hi": "एक सरल रेखा",
    },
]


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def is_filler_text(text: str) -> bool:
    n = _norm(text)
    n = n.strip(string.punctuation + " ")
    return n in FILLER_WORDS


def pair_is_natural(pair: dict) -> list[str]:
    fails = []
    for side in ("a_en", "b_en", "a_hi", "b_hi"):
        if is_filler_text(pair.get(side) or ""):
            fails.append(f"{side} is filler: {pair.get(side)}")
    if _norm(pair.get("a_en") or "") == _norm(pair.get("b_en") or ""):
        fails.append("A and B are the same")
    if not pair.get("chapter_id") or not pair.get("topic_id") or not pair.get("source_page"):
        fails.append("missing book trace")
    return fails


def allowed_pairs(allowed: AllowedContentSet) -> list[dict]:
    ch = set(allowed.allowed_chapter_ids)
    topics = set(allowed.allowed_topic_ids)
    out = []
    for p in NATURAL_PAIRS:
        if p["chapter_id"] not in ch:
            continue
        if topics and p["topic_id"] not in topics:
            continue
        if pair_is_natural(p):
            continue
        out.append(p)
    return out


def build_match_question(
    allowed: AllowedContentSet,
    n_pairs: int = 6,
    used_ids: set[str] | None = None,
    seed: int | None = None,
) -> dict:
    """Build one MATCH_COLUMNS item from natural book pairs. Never chops an exercise."""
    rng = random.Random(seed)
    used_ids = used_ids if used_ids is not None else set()
    pool = [p for p in allowed_pairs(allowed) if p["pair_id"] not in used_ids]
    rng.shuffle(pool)
    chosen: list[dict] = []
    b_seen: set[str] = set()
    a_seen: set[str] = set()
    for p in pool:
        a_key = _norm(p["a_en"])
        b_key = _norm(p["b_en"])
        if a_key in a_seen or b_key in b_seen:
            continue
        chosen.append(p)
        a_seen.add(a_key)
        b_seen.add(b_key)
        used_ids.add(p["pair_id"])
        if len(chosen) == n_pairs:
            break
    if len(chosen) < n_pairs:
        raise ValueError(
            f"Not enough natural MATCH pairs in allowed chapters "
            f"({len(chosen)}/{n_pairs}). Refusing to force filler pairs."
        )

    labels = list(string.ascii_lowercase[:n_pairs])
    b_order = list(range(n_pairs))
    rng.shuffle(b_order)
    column_a = []
    column_b = [None] * n_pairs
    mapping = []
    pair_traces = []
    for i, p in enumerate(chosen):
        a_label = str(i + 1)
        b_label = labels[b_order[i]]
        column_a.append(f"({a_label}) {p['a_hi']}")
        column_b[b_order[i]] = f"({b_label}) {p['b_hi']}"
        mapping.append(f"({a_label})-({b_label})")
        pair_traces.append(
            {
                "a_index": a_label,
                "b_label": b_label,
                "a_hi": p["a_hi"],
                "b_hi": p["b_hi"],
                "a_en": p["a_en"],
                "b_en": p["b_en"],
                "chapter_id": p["chapter_id"],
                "topic_id": p["topic_id"],
                "source_page": p["source_page"],
                "source_ref": p["source_ref"],
                "pair_id": p["pair_id"],
            }
        )
    column_b = [x for x in column_b if x is not None]
    return {
        "column_a": column_a,
        "column_b": column_b,
        "answer_mapping": mapping,
        "pairs": pair_traces,
        "source_type": "book",
        "format_id": "MATCH_COLUMNS",
    }


def judge_match_question(q: dict, allowed: AllowedContentSet) -> dict:
    fails = []
    pairs = q.get("pairs") or []
    if len(pairs) != 6:
        fails.append(f"expected 6 pairs, got {len(pairs)}")
    a_vals = [_norm(p.get("a_en") or p.get("a_hi") or "") for p in pairs]
    b_vals = [_norm(p.get("b_en") or p.get("b_hi") or "") for p in pairs]
    if len(set(a_vals)) != len(a_vals):
        fails.append("duplicate Column A")
    if len(set(b_vals)) != len(b_vals):
        fails.append("duplicate Column B (not one-to-one)")
    for p in pairs:
        if is_filler_text(p.get("a_en") or "") or is_filler_text(p.get("a_hi") or ""):
            fails.append(f"filler A: {p.get('a_en')}")
        if is_filler_text(p.get("b_en") or "") or is_filler_text(p.get("b_hi") or ""):
            fails.append(f"filler B: {p.get('b_en')}")
        if p.get("chapter_id") not in allowed.allowed_chapter_ids:
            fails.append(f"chapter {p.get('chapter_id')} outside allowed set")
        if allowed.allowed_topic_ids and p.get("topic_id") not in allowed.allowed_topic_ids:
            fails.append(f"topic {p.get('topic_id')} outside allowed set")
        if not p.get("source_page") or not p.get("source_ref"):
            fails.append(f"missing book trace for {p.get('pair_id')}")
    mapping = q.get("answer_mapping") or []
    if len(mapping) != len(pairs):
        fails.append("answer mapping length mismatch")
    oos = [p for p in pairs if p.get("chapter_id") not in allowed.allowed_chapter_ids]
    return {
        "result": "FAIL" if fails else "PASS",
        "fails": fails,
        "out_of_syllabus_count": len(oos),
    }
