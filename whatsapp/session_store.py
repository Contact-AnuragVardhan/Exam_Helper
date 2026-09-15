from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy.exc import IntegrityError

from database.models import ExamHelperProcessedMessageRow, ExamHelperSessionRow
from database.session import db_session, new_session


STATE_MAIN = "MAIN"
STATE_CONFIGURE = "CONFIGURE"
STATE_CONFIG_SUBJECT = "CONFIG_SUBJECT"
STATE_CONFIG_GRADE = "CONFIG_GRADE"
STATE_CONFIG_CLASS = "CONFIG_CLASS"
STATE_CONFIG_LANGUAGE = "CONFIG_LANGUAGE"
STATE_CREATE = "CREATE"
STATE_SELECT_CHAPTERS = "SELECT_CHAPTERS"
STATE_SELECT_TOPICS = "SELECT_TOPICS"
STATE_REVIEW = "REVIEW"
STATE_POST_GENERATE = "POST_GENERATE"
STATE_MY_EXAMS = "MY_EXAMS"
STATE_MY_EXAM_DETAIL = "MY_EXAM_DETAIL"
STATE_FEEDBACK = "FEEDBACK"
STATE_HELP = "HELP"

PARENT_STATE = {
    STATE_CONFIGURE: STATE_MAIN,
    STATE_CONFIG_SUBJECT: STATE_CONFIGURE,
    STATE_CONFIG_GRADE: STATE_CONFIGURE,
    STATE_CONFIG_CLASS: STATE_CONFIGURE,
    STATE_CONFIG_LANGUAGE: STATE_CONFIGURE,
    STATE_CREATE: STATE_MAIN,
    STATE_SELECT_CHAPTERS: STATE_CREATE,
    STATE_SELECT_TOPICS: STATE_CREATE,
    STATE_REVIEW: STATE_CREATE,
    STATE_POST_GENERATE: STATE_MAIN,
    STATE_MY_EXAMS: STATE_MAIN,
    STATE_MY_EXAM_DETAIL: STATE_MY_EXAMS,
    STATE_FEEDBACK: STATE_MAIN,
    STATE_HELP: STATE_MAIN,
}


def _normalize_wa_id(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


@dataclass
class WhatsAppSession:
    wa_id: str
    teacher_id: str
    state: str = STATE_MAIN
    subject: str = "Mathematics"
    grade: int = 10
    class_id: str = "10-A"
    output_language: str = "Hindi"
    selected_chapter_ids: list[str] = field(default_factory=list)
    selected_topic_ids: list[str] | None = None
    pending_subject: str = "Mathematics"
    pending_grade: int = 10
    pending_class_id: str = "10-A"
    pending_language: str = "Hindi"
    last_exam_id: str = ""
    detail_exam_id: str = ""
    feedback_exam_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WhatsAppSession":
        topic_ids = data.get("selected_topic_ids")
        return cls(
            wa_id=_normalize_wa_id(data.get("wa_id")),
            teacher_id=str(data.get("teacher_id") or ""),
            state=str(data.get("state") or STATE_MAIN),
            subject=str(data.get("subject") or "Mathematics"),
            grade=int(data.get("grade") or 10),
            class_id=str(data.get("class_id") or "10-A"),
            output_language=str(data.get("output_language") or "Hindi"),
            selected_chapter_ids=list(data.get("selected_chapter_ids") or []),
            selected_topic_ids=None if topic_ids is None else list(topic_ids),
            pending_subject=str(data.get("pending_subject") or data.get("subject") or "Mathematics"),
            pending_grade=int(data.get("pending_grade") or data.get("grade") or 10),
            pending_class_id=str(data.get("pending_class_id") or data.get("class_id") or "10-A"),
            pending_language=str(data.get("pending_language") or data.get("output_language") or "Hindi"),
            last_exam_id=str(data.get("last_exam_id") or ""),
            detail_exam_id=str(data.get("detail_exam_id") or ""),
            feedback_exam_id=str(data.get("feedback_exam_id") or ""),
        )


class SessionStore:
    """PostgreSQL-backed WhatsApp session and deduplication store."""

    def already_processed(self, message_id: str | None) -> bool:
        if not message_id:
            return False
        with db_session() as db:
            return db.get(ExamHelperProcessedMessageRow, str(message_id)) is not None

    def mark_processed(self, message_id: str | None, wa_id: str = "") -> None:
        if not message_id:
            return
        # Separate transaction so a concurrent duplicate cannot claim the same PK.
        db = new_session()
        try:
            if db.get(ExamHelperProcessedMessageRow, str(message_id)) is None:
                db.add(
                    ExamHelperProcessedMessageRow(
                        message_id=str(message_id),
                        wa_id=_normalize_wa_id(wa_id),
                    )
                )
                db.commit()
        except IntegrityError:
            db.rollback()
        finally:
            db.close()

    def get(self, wa_id: str) -> WhatsAppSession | None:
        key = _normalize_wa_id(wa_id)
        if not key:
            return None
        with db_session() as db:
            row = db.get(ExamHelperSessionRow, key)
            if row is None:
                return None
            payload = dict(row.payload or {})
            payload.setdefault("wa_id", row.wa_id)
            payload.setdefault("teacher_id", row.teacher_id)
            payload.setdefault("state", row.state)
            return WhatsAppSession.from_dict(payload)

    def put(self, session: WhatsAppSession) -> WhatsAppSession:
        session.wa_id = _normalize_wa_id(session.wa_id)
        with db_session() as db:
            row = db.get(ExamHelperSessionRow, session.wa_id)
            if row is None:
                row = ExamHelperSessionRow(
                    wa_id=session.wa_id,
                    teacher_id=session.teacher_id,
                    state=session.state,
                    payload=session.to_dict(),
                )
                db.add(row)
            else:
                row.teacher_id = session.teacher_id
                row.state = session.state
                row.payload = session.to_dict()
        return session

    def get_or_create(
        self,
        wa_id: str,
        teacher_id: str,
        *,
        subject: str = "Mathematics",
        grade: int = 10,
        class_id: str = "10-A",
        output_language: str = "Hindi",
    ) -> WhatsAppSession:
        key = _normalize_wa_id(wa_id)
        existing = self.get(key)
        if existing is not None:
            if existing.teacher_id != str(teacher_id):
                existing.teacher_id = str(teacher_id)
                existing.state = STATE_MAIN
                existing.subject = subject
                existing.grade = grade
                existing.class_id = class_id
                existing.output_language = output_language
                existing.pending_subject = subject
                existing.pending_grade = grade
                existing.pending_class_id = class_id
                existing.pending_language = output_language
                existing.selected_chapter_ids = []
                existing.selected_topic_ids = None
                existing.last_exam_id = ""
                existing.detail_exam_id = ""
                existing.feedback_exam_id = ""
                self.put(existing)
            return existing
        session = WhatsAppSession(
            wa_id=key,
            teacher_id=str(teacher_id),
            subject=subject,
            grade=grade,
            class_id=class_id,
            output_language=output_language,
            pending_subject=subject,
            pending_grade=grade,
            pending_class_id=class_id,
            pending_language=output_language,
        )
        return self.put(session)
