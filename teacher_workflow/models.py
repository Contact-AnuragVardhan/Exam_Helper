from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ALLOWED_GRADES = (10,)
ALLOWED_SUBJECTS = ("Mathematics", "English")
ALLOWED_OUTPUT_LANGUAGES = ("English", "Hindi")


def normalize_output_language(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("en"):
        return "English"
    if raw.startswith("hi"):
        return "Hindi"
    return "Hindi"

STATUS_DRAFT = "DRAFT"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"
STATUS_APPROVED = "APPROVED"

TEACHER_STATUSES = (STATUS_DRAFT, STATUS_SUBMITTED)
FEEDBACK_STATUSES = (STATUS_CHANGES_REQUESTED, STATUS_APPROVED)


@dataclass
class TeacherProfile:
    teacher_id: str = "T001"
    teacher_name: str = "Demo Teacher"
    grade: int = 10
    subject: str = "Mathematics"
    class_id: str = "10-A"
    output_language: str = "Hindi"
    whatsapp_number: str = ""
    school_name: str = ""
    preferred_language: str = "English"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionConfig:
    teacher_id: str
    teacher_name: str
    grade: int
    subject: str
    class_id: str
    output_language: str = "Hindi"
    selected_chapter_ids: list[str] = field(default_factory=list)
    selected_topic_ids: list[str] | None = None

    @classmethod
    def from_profile(cls, profile: TeacherProfile) -> "SessionConfig":
        return cls(
            teacher_id=profile.teacher_id,
            teacher_name=profile.teacher_name,
            grade=int(profile.grade),
            subject=profile.subject,
            class_id=profile.class_id,
            output_language=normalize_output_language(getattr(profile, "output_language", None)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChapterChoice:
    chapter_id: str
    chapter_number: int
    chapter_name: str
    kind: str = ""


@dataclass
class TopicChoice:
    topic_id: str
    chapter_id: str
    chapter_name: str
    topic_name: str
    section_number: str = ""


@dataclass
class ExamRecord:
    exam_id: str
    teacher_id: str
    teacher_name: str
    grade: int
    subject: str
    class_id: str
    selected_chapters: list[str]
    selected_topics: list[str]
    exam_pdf_path: str
    answer_key_pdf_path: str
    created_at: str
    status: str = STATUS_DRAFT
    principal_feedback: str = ""
    output_dir: str = ""
    output_language: str = "Hindi"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExamRecord":
        return cls(
            exam_id=str(data.get("exam_id") or ""),
            teacher_id=str(data.get("teacher_id") or ""),
            teacher_name=str(data.get("teacher_name") or ""),
            grade=int(data.get("grade") or 10),
            subject=str(data.get("subject") or ""),
            class_id=str(data.get("class_id") or ""),
            output_language=normalize_output_language(data.get("output_language")),
            selected_chapters=list(data.get("selected_chapters") or []),
            selected_topics=list(data.get("selected_topics") or []),
            exam_pdf_path=str(data.get("exam_pdf_path") or ""),
            answer_key_pdf_path=str(data.get("answer_key_pdf_path") or ""),
            created_at=str(data.get("created_at") or ""),
            status=str(data.get("status") or STATUS_DRAFT),
            principal_feedback=str(data.get("principal_feedback") or ""),
            output_dir=str(data.get("output_dir") or ""),
        )
