from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TeacherProfileRow(Base):
    """Mapping for the existing Teacher Helper teacher_profile table."""

    __tablename__ = "teacher_profile"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    whatsapp_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    teacher_name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_grade: Mapped[str] = mapped_column(String(100), nullable=False)
    default_subject: Mapped[str] = mapped_column(String(100), nullable=False)
    school_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(50), nullable=False, default="English")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ExamHelperSessionRow(Base):
    __tablename__ = "exam_helper_sessions"

    wa_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="MAIN", index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ExamHelperProcessedMessageRow(Base):
    __tablename__ = "exam_helper_processed_messages"

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class ExamHelperExamRow(Base):
    __tablename__ = "exam_helper_exams"

    exam_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    teacher_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    class_id: Mapped[str] = mapped_column(String(100), nullable=False)
    output_language: Mapped[str] = mapped_column(String(50), nullable=False, default="Hindi")
    selected_chapters: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT", index=True)
    principal_feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Full generated exam payload and artifacts are persisted in PostgreSQL.
    exam_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exam_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    blueprint_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    llm_usage_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    allowed_content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exam_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_key_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    validation_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    exam_pdf: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    answer_key_pdf: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
