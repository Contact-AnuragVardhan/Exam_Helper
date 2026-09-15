from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .logger import get_logger
from .paths import output_exams_dir
from .content_gate import syllabus_display_from_exam
from .renderer import render_answer_key_pdf, render_answer_key_txt, render_exam_pdf, render_exam_txt
from .validator import report_text


log = get_logger("exam_store")


def make_exam_id(prefix: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in prefix)[:40]
    return f"{ts}_{safe}"


def save_exam(exam: dict, blueprint: dict, report: dict, exam_id: str | None = None) -> Path:
    exam_id = exam_id or exam.get("exam_id") or make_exam_id("math10")
    exam["exam_id"] = exam_id
    if not (exam.get("syllabus") or {}).get("groups"):
        exam["syllabus"] = syllabus_display_from_exam(exam)
    out = output_exams_dir() / exam_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "exam.json").write_text(json.dumps(exam, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "blueprint.json").write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "exam.txt").write_text(render_exam_txt(exam), encoding="utf-8")
    render_exam_pdf(exam, out / "exam.pdf")
    (out / "answer_key.txt").write_text(render_answer_key_txt(exam), encoding="utf-8")
    render_answer_key_pdf(exam, out / "answer_key.pdf")
    (out / "validation_report.txt").write_text(report_text(report), encoding="utf-8")
    (out / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved exam %s to %s", exam_id, out)
    return out


def load_exam(exam_id: str) -> dict:
    path = output_exams_dir() / exam_id / "exam.json"
    if not path.exists():
        raise FileNotFoundError(f"Exam not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
