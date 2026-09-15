from __future__ import annotations

from services.logger import get_logger
from teacher_workflow.models import TeacherProfile

from database.session import db_session
from database.teacher_repository import TeacherRepository, digits_only


log = get_logger("whatsapp.teachers")


def normalize_wa_id(value: str | None) -> str:
    return digits_only(value)


def resolve_teacher_profile(wa_id: str | None) -> TeacherProfile | None:
    """Resolve an inbound WhatsApp sender to the existing teacher_profile DB row."""
    key = normalize_wa_id(wa_id)
    if not key:
        return None

    try:
        with db_session() as db:
            repo = TeacherRepository(db)
            row = repo.get_by_whatsapp_number(key)
            if row is None:
                return None
            profile = repo.to_workflow_profile(row)
            log.info(
                "teacher resolved wa_id=***%s teacher_id=%s teacher_name=%s",
                key[-4:],
                profile.teacher_id,
                profile.teacher_name,
            )
            return profile
    except Exception:
        log.exception("teacher lookup failed wa_id=***%s", key[-4:])
        raise


def resolve_teacher_id(wa_id: str | None) -> str | None:
    """Backward-compatible helper. WhatsApp routing now resolves the full DB profile."""
    profile = resolve_teacher_profile(wa_id)
    return profile.teacher_id if profile else None
