from __future__ import annotations

import re


RESIDUAL_SUB_RE = re.compile(
    r"^\s*\(((?:ii|iii|iv|v|vi|vii|viii|ix|x)|[2-9])\)\s+",
    re.I,
)
TRAILING_RESIDUAL_RE = re.compile(
    r"(?im)^[ \t]*Column B[^\n]*\n(?:[ \t]*\([0-9A-Za-z]+\)[^\n]*\n){2,}[ \t]*\((?:ii|iii|iv|v|vi|[2-9])\)\s+\S"
)


def is_match_item(item: dict) -> bool:
    return (item.get("format_id") or "").upper() == "MATCH_COLUMNS"


def _clean_cells(values) -> list[str]:
    out = []
    for raw in values or []:
        text = str(raw).strip()
        if text:
            out.append(text)
    return out


def match_table_payload(item: dict) -> dict | None:
    """Student-facing MATCH_COLUMNS payload only. Leaves source metadata untouched."""
    if not is_match_item(item):
        return None
    col_a = _clean_cells(item.get("match_column_a"))
    col_b = _clean_cells(item.get("match_column_b"))
    if len(col_a) < 2 or len(col_b) < 2:
        pairs = item.get("match_pairs") or []
        if len(pairs) >= 2:
            col_a = []
            col_b = []
            for i, p in enumerate(pairs, start=1):
                a_txt = (p.get("a_hi") or p.get("a_en") or "").strip()
                b_txt = (p.get("b_hi") or p.get("b_en") or "").strip()
                if not a_txt or not b_txt:
                    continue
                a_idx = p.get("a_index") or str(i)
                b_lab = (p.get("b_label") or "").strip() or chr(96 + i)
                col_a.append(f"({a_idx}) {a_txt}")
                col_b.append(f"({b_lab}) {b_txt}")
    if len(col_a) < 2 or not col_b:
        return None
    n = min(len(col_a), len(col_b))
    return {
        "column_a": col_a[:n] if len(col_b) >= len(col_a) else col_a,
        "column_b": col_b,
        "rows": _paired_rows(col_a, col_b),
        "mapping": list(item.get("answer_mapping") or []),
        "pairs": list(item.get("match_pairs") or []),
    }


def _paired_rows(col_a: list[str], col_b: list[str]) -> list[list[str]]:
    n = max(len(col_a), len(col_b))
    rows = []
    for i in range(n):
        rows.append(
            [
                col_a[i] if i < len(col_a) else "",
                col_b[i] if i < len(col_b) else "",
            ]
        )
    return rows


def is_residual_match_item(item: dict) -> bool:
    """True when this MATCH_COLUMNS slot is leftover source text, not the table."""
    if not is_match_item(item):
        return False
    return match_table_payload(item) is None


def mapping_lines(item: dict) -> list[str]:
    payload = match_table_payload(item) or {}
    mapping = list(payload.get("mapping") or [])
    if not mapping:
        for p in payload.get("pairs") or []:
            a_idx = str(p.get("a_index") or "").strip()
            b_lab = str(p.get("b_label") or "").strip()
            if a_idx and b_lab:
                mapping.append(f"({a_idx})-({b_lab})")
    lines = []
    for raw in mapping:
        text = str(raw).strip()
        m = re.search(r"\(?([0-9]+)\)?\s*[-–>:]+\s*\(?([A-Za-z])\)?", text)
        if m:
            lines.append(f"{m.group(1)} -> {m.group(2).upper()}")
            continue
        m = re.search(r"\(([0-9]+)\)\s*[-–]\s*\(([A-Za-z])\)", text)
        if m:
            lines.append(f"{m.group(1)} -> {m.group(2).upper()}")
        else:
            lines.append(text)
    return lines


def student_text_has_residual(text: str) -> bool:
    if TRAILING_RESIDUAL_RE.search(text or ""):
        return True
    # After a match table, a leftover roman subquestion must not appear
    # before the next main question.
    blocks = re.split(r"(?m)^(?=Q\d+\.)", text or "")
    for block in blocks:
        if "Column A" not in block or "Column B" not in block:
            continue
        after_header = block.split("Column B", 1)[-1]
        if RESIDUAL_SUB_RE.search(after_header):
            return True
        if re.search(r"(?im)^[ \t]*\((?:ii|iii|iv|v|vi)\)\s+\S", after_header):
            return True
    return False


def validate_match_payload(item: dict) -> dict:
    payload = match_table_payload(item)
    fails = []
    if not payload:
        return {"result": "FAIL", "fails": ["no printable MATCH_COLUMNS table"]}
    col_a = payload["column_a"]
    col_b = payload["column_b"]
    if len(col_a) < 2:
        fails.append("Column A has fewer than 2 entries")
    if len(col_b) < 2:
        fails.append("Column B is missing the option set")
    mapping = mapping_lines(item)
    if mapping and len(set(mapping)) != len(mapping):
        fails.append("duplicate-answer ambiguity")
    b_labels = []
    for cell in col_b:
        m = re.match(r"^\(([A-Za-z0-9]+)\)", cell.strip())
        if m:
            b_labels.append(m.group(1).lower())
    if b_labels and len(set(b_labels)) != len(b_labels):
        fails.append("duplicate Column B labels")
    mapped_b = []
    for line in mapping:
        m = re.search(r"->\s*([A-Z])", line)
        if m:
            mapped_b.append(m.group(1).lower())
    if mapped_b and len(set(mapped_b)) != len(mapped_b):
        fails.append("duplicate-answer ambiguity")
    if mapping and len(mapping) != len(col_a):
        fails.append("each Column A item does not have exactly one match")
    return {"result": "FAIL" if fails else "PASS", "fails": fails, "payload": payload}
