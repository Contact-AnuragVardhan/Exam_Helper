from __future__ import annotations

import re

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from teacher_workflow.models import TeacherProfile

from .models import TeacherProfileRow


def digits_only(phone_number: str | None) -> str:
    return re.sub(r"\D", "", str(phone_number or ""))


def canonical_whatsapp_number(phone_number: str | None) -> str:
    digits = digits_only(phone_number)
    return f"+{digits}" if digits else ""


def parse_grade(value: str | int | None) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def normalize_exam_subject(value: str | None) -> str:
    raw = str(value or "").strip()
    low = raw.casefold()
    if low.startswith("math") or "mathemat" in low:
        return "Mathematics"
    if low.startswith("eng"):
        return "English"
    return raw


def default_exam_output_language(subject: str) -> str:
    return "English" if subject == "English" else "Hindi"


class TeacherRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_whatsapp_number(self, whatsapp_number: str | None) -> TeacherProfileRow | None:
        digits = digits_only(whatsapp_number)
        canonical = canonical_whatsapp_number(whatsapp_number)
        if not digits:
            return None

        return (
            self.db.query(TeacherProfileRow)
            .filter(
                or_(
                    TeacherProfileRow.whatsapp_number == canonical,
                    TeacherProfileRow.whatsapp_number == digits,
                    func.replace(TeacherProfileRow.whatsapp_number, "+", "") == digits,
                )
            )
            .first()
        )

    def to_workflow_profile(self, row: TeacherProfileRow) -> TeacherProfile:
        grade = parse_grade(row.default_grade)
        subject = normalize_exam_subject(row.default_subject)
        class_id = f"{grade}-A" if grade else "10-A"
        return TeacherProfile(
            teacher_id=str(row.id),
            teacher_name=row.teacher_name,
            grade=grade or 10,
            subject=subject or "Mathematics",
            class_id=class_id,
            output_language=default_exam_output_language(subject),
            whatsapp_number=canonical_whatsapp_number(row.whatsapp_number),
            school_name=(row.school_name or "").strip(),
            preferred_language=(row.preferred_language or "English").strip() or "English",
        )
