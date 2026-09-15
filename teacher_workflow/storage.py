from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.models import ExamHelperExamRow
from database.session import db_session

from .models import ExamRecord, TeacherProfile, normalize_output_language


def _json_safe(value: Any, default):
    if value is None:
        return default
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return default


def _parse_created_at(value: str | None) -> datetime:
    raw = str(value or "").strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _row_to_record(row: ExamHelperExamRow) -> ExamRecord:
    created = row.created_at.isoformat(timespec="seconds") if row.created_at else ""
    return ExamRecord(
        exam_id=row.exam_id,
        teacher_id=row.teacher_id,
        teacher_name=row.teacher_name,
        grade=row.grade,
        subject=row.subject,
        class_id=row.class_id,
        selected_chapters=list(row.selected_chapters or []),
        selected_topics=list(row.selected_topics or []),
        exam_pdf_path=f"db://exam_helper_exams/{row.exam_id}/exam.pdf",
        answer_key_pdf_path=f"db://exam_helper_exams/{row.exam_id}/answer_key.pdf",
        created_at=created,
        status=row.status,
        principal_feedback=row.principal_feedback or "",
        output_dir=f"db://exam_helper_exams/{row.exam_id}",
        output_language=normalize_output_language(row.output_language),
    )


def load_teacher_profile() -> TeacherProfile:
    """Local-terminal helper. Production WhatsApp always resolves the sender from DB."""
    from database.teacher_repository import TeacherRepository

    wa_id = os.getenv("LOCAL_TEACHER_WHATSAPP_NUMBER", "").strip()
    if not wa_id:
        raise RuntimeError(
            "LOCAL_TEACHER_WHATSAPP_NUMBER is required for terminal mode. "
            "Teacher profiles are database-backed; config/teacher_profile.json is no longer used."
        )
    with db_session() as db:
        repo = TeacherRepository(db)
        row = repo.get_by_whatsapp_number(wa_id)
        if row is None:
            raise RuntimeError(f"No teacher_profile row found for {wa_id}.")
        return repo.to_workflow_profile(row)


def load_exam_records() -> list[ExamRecord]:
    with db_session() as db:
        rows = db.query(ExamHelperExamRow).order_by(ExamHelperExamRow.created_at.desc()).all()
        return [_row_to_record(row) for row in rows]


def save_exam_records(records: list[ExamRecord]) -> None:
    """Compatibility helper used by local tests/maintenance; production uses upsert."""
    wanted = {r.exam_id for r in records}
    with db_session() as db:
        for row in db.query(ExamHelperExamRow).all():
            if row.exam_id not in wanted:
                db.delete(row)
        for record in records:
            row = db.get(ExamHelperExamRow, record.exam_id)
            if row is None:
                row = ExamHelperExamRow(exam_id=record.exam_id)
                db.add(row)
            _apply_record(row, record)


def _apply_record(row: ExamHelperExamRow, record: ExamRecord) -> None:
    row.teacher_id = record.teacher_id
    row.teacher_name = record.teacher_name
    row.grade = int(record.grade)
    row.subject = record.subject
    row.class_id = record.class_id
    row.output_language = normalize_output_language(record.output_language)
    row.selected_chapters = list(record.selected_chapters or [])
    row.selected_topics = list(record.selected_topics or [])
    row.status = record.status
    row.principal_feedback = record.principal_feedback or ""
    if row.created_at is None:
        row.created_at = _parse_created_at(record.created_at)


def upsert_exam_record(record: ExamRecord, artifacts: dict[str, Any] | None = None) -> ExamRecord:
    with db_session() as db:
        row = db.get(ExamHelperExamRow, record.exam_id)
        if row is None:
            row = ExamHelperExamRow(exam_id=record.exam_id)
            db.add(row)
        _apply_record(row, record)

        if artifacts is not None:
            row.exam_config = _json_safe(artifacts.get("exam_config"), {})
            row.exam_json = _json_safe(artifacts.get("exam_json"), {})
            row.blueprint_json = _json_safe(artifacts.get("blueprint_json"), {})
            row.validation_json = _json_safe(artifacts.get("validation_json"), {})
            row.llm_usage_json = _json_safe(artifacts.get("llm_usage_json"), {})
            row.allowed_content_json = _json_safe(artifacts.get("allowed_content_json"), {})
            row.exam_text = str(artifacts.get("exam_text") or "")
            row.answer_key_text = str(artifacts.get("answer_key_text") or "")
            row.validation_text = str(artifacts.get("validation_text") or "")
            exam_pdf = artifacts.get("exam_pdf")
            answer_pdf = artifacts.get("answer_key_pdf")
            if exam_pdf is not None:
                row.exam_pdf = bytes(exam_pdf)
            if answer_pdf is not None:
                row.answer_key_pdf = bytes(answer_pdf)
    return record


def get_exam_record(exam_id: str) -> ExamRecord | None:
    with db_session() as db:
        row = db.get(ExamHelperExamRow, exam_id)
        return _row_to_record(row) if row is not None else None


def list_teacher_exams(teacher_id: str) -> list[ExamRecord]:
    with db_session() as db:
        rows = (
            db.query(ExamHelperExamRow)
            .filter(ExamHelperExamRow.teacher_id == str(teacher_id))
            .order_by(ExamHelperExamRow.created_at.desc())
            .all()
        )
        return [_row_to_record(row) for row in rows]


def list_feedback_exams(teacher_id: str) -> list[ExamRecord]:
    from .models import FEEDBACK_STATUSES

    with db_session() as db:
        rows = (
            db.query(ExamHelperExamRow)
            .filter(
                ExamHelperExamRow.teacher_id == str(teacher_id),
                ExamHelperExamRow.status.in_(FEEDBACK_STATUSES),
            )
            .order_by(ExamHelperExamRow.created_at.desc())
            .all()
        )
        return [_row_to_record(row) for row in rows]


def get_exam_pdf_bytes(exam_id: str) -> bytes:
    with db_session() as db:
        row = db.get(ExamHelperExamRow, exam_id)
        if row is None or not row.exam_pdf:
            raise ValueError("Exam PDF is not available.")
        return bytes(row.exam_pdf)


def get_answer_key_pdf_bytes(exam_id: str) -> bytes:
    with db_session() as db:
        row = db.get(ExamHelperExamRow, exam_id)
        if row is None or not row.answer_key_pdf:
            raise ValueError("Answer key PDF is not available.")
        return bytes(row.answer_key_pdf)


def get_exam_artifacts(exam_id: str) -> dict[str, Any]:
    with db_session() as db:
        row = db.get(ExamHelperExamRow, exam_id)
        if row is None:
            raise ValueError("Exam not found.")
        return {
            "exam_config": row.exam_config or {},
            "exam_json": row.exam_json or {},
            "blueprint_json": row.blueprint_json or {},
            "validation_json": row.validation_json or {},
            "llm_usage_json": row.llm_usage_json or {},
            "allowed_content_json": row.allowed_content_json or {},
            "exam_text": row.exam_text or "",
            "answer_key_text": row.answer_key_text or "",
            "validation_text": row.validation_text or "",
            "exam_pdf": bytes(row.exam_pdf or b""),
            "answer_key_pdf": bytes(row.answer_key_pdf or b""),
        }


def materialize_exam_pdf(exam_id: str, *, answer_key: bool = False) -> Path:
    content = get_answer_key_pdf_bytes(exam_id) if answer_key else get_exam_pdf_bytes(exam_id)
    name = "answer_key.pdf" if answer_key else "exam.pdf"
    directory = Path(tempfile.gettempdir()) / "exam_helper" / exam_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content)
    return path
