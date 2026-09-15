from __future__ import annotations

from datetime import datetime

from services.logger import get_logger
from teacher_workflow.models import ALLOWED_GRADES, ALLOWED_SUBJECTS, STATUS_DRAFT, TeacherProfile
from teacher_workflow.service import TeacherWorkflow

from .client import WhatsAppClient, mask_wa_id
from .message_parser import (
    is_all,
    is_back,
    is_cancel,
    is_greeting,
    is_menu,
    normalize_text,
    parse_index_list,
    parse_menu_number,
)
from .session_store import (
    PARENT_STATE,
    STATE_CONFIG_CLASS,
    STATE_CONFIG_GRADE,
    STATE_CONFIG_LANGUAGE,
    STATE_CONFIG_SUBJECT,
    STATE_CONFIGURE,
    STATE_CREATE,
    STATE_FEEDBACK,
    STATE_HELP,
    STATE_MAIN,
    STATE_MY_EXAM_DETAIL,
    STATE_MY_EXAMS,
    STATE_POST_GENERATE,
    STATE_REVIEW,
    STATE_SELECT_CHAPTERS,
    STATE_SELECT_TOPICS,
    SessionStore,
    WhatsAppSession,
)
from .teachers import resolve_teacher_profile


log = get_logger("whatsapp.adapter")

UNREGISTERED = (
    "This number is not registered for Teacher EXAM.\n"
    "Please contact the administrator."
)
UNSUPPORTED = "Please send a text reply using the menu numbers."
UNSUPPORTED_PROFILE = (
    "Your teacher profile is registered, but Teacher EXAM currently supports only "
    "Grade 10 Mathematics and English."
)
DATABASE_ERROR = (
    "Teacher EXAM could not load your teacher profile right now. "
    "Please try again later or contact the administrator."
)
UNKNOWN_OPTION = "Reply with a number from the menu."
BAD_SELECTION = "That selection is not valid. Reply with numbers like 1,2 or ALL."
HELP_TEXT = (
    "HELP\n"
    "\n"
    "1. Configure Exam if you need to change Subject, Grade, Class, or Output Language.\n"
    "2. Create Exam.\n"
    "3. Select Chapters.\n"
    "4. Select Topics or use ALL.\n"
    "5. Generate.\n"
    "6. Review PDF.\n"
    "7. Submit to Principal.\n"
    "\n"
    "Send MENU anytime to return to Main Menu."
)
POST_GENERATE_MENU = (
    "1. View Answer Key\n"
    "2. Save Exam\n"
    "3. Submit to Principal\n"
    "4. Create Another Exam\n"
    "0. Main Menu"
)


class WhatsAppAdapter:
    """Menu/state routing only. All exam work goes through TeacherWorkflow."""

    def __init__(
        self,
        client: WhatsAppClient | None = None,
        store: SessionStore | None = None,
        workflow_factory=TeacherWorkflow,
    ) -> None:
        self.client = client or WhatsAppClient()
        self.store = store or SessionStore()
        self.workflow_factory = workflow_factory

    def handle_text(self, wa_id: str, text: str, message_id: str | None = None) -> list[str]:
        if self.store.already_processed(message_id):
            log.info(
                "duplicate ignored wa_id=%s message_id=%s",
                mask_wa_id(wa_id),
                message_id,
            )
            return []
        self.store.mark_processed(message_id, wa_id)
        before = len(self.client.sent_texts)
        self._handle_text(wa_id, text)
        return [item.text for item in self.client.sent_texts[before:]]

    def handle_unsupported(self, wa_id: str, message_id: str | None = None) -> list[str]:
        if self.store.already_processed(message_id):
            return []
        self.store.mark_processed(message_id, wa_id)
        try:
            profile = resolve_teacher_profile(wa_id)
        except Exception:
            self.client.send_text(wa_id, DATABASE_ERROR)
            return [self.client.last_text()]
        if profile is None:
            self.client.send_text(wa_id, UNREGISTERED)
        elif not self._profile_supported(profile):
            self.client.send_text(wa_id, UNSUPPORTED_PROFILE)
        else:
            self.client.send_text(wa_id, UNSUPPORTED)
        return [self.client.last_text()]

    def _handle_text(self, wa_id: str, text: str) -> None:
        try:
            profile = resolve_teacher_profile(wa_id)
        except Exception:
            self.client.send_text(wa_id, DATABASE_ERROR)
            log.exception("teacher profile database lookup failed wa_id=%s", mask_wa_id(wa_id))
            return
        if profile is None:
            self.client.send_text(wa_id, UNREGISTERED)
            log.info("unregistered wa_id=%s action=reject", mask_wa_id(wa_id))
            return
        if not self._profile_supported(profile):
            self.client.send_text(wa_id, UNSUPPORTED_PROFILE)
            log.info(
                "unsupported teacher profile wa_id=%s grade=%s subject=%s",
                mask_wa_id(wa_id),
                profile.grade,
                profile.subject,
            )
            return
        raw = normalize_text(text)
        session = self.store.get_or_create(
            wa_id,
            profile.teacher_id,
            subject=profile.subject,
            grade=profile.grade,
            class_id=profile.class_id,
            output_language=profile.output_language,
        )
        wf = self._workflow(session, profile)
        if not raw:
            self._reply_unknown(wa_id, session, wf)
            self._persist(session, wf)
            return
        if is_cancel(raw) or is_menu(raw) or is_greeting(raw):
            if is_cancel(raw):
                self._cancel(session, wf)
            session.state = STATE_MAIN
            self._send_main(wa_id, wf)
            self._persist(session, wf)
            self._log(wa_id, session, "main")
            return
        if is_back(raw):
            self._go_back(session, wf)
            self._show_state(wa_id, session, wf)
            self._persist(session, wf)
            self._log(wa_id, session, "back")
            return
        handler = {
            STATE_MAIN: self._on_main,
            STATE_CONFIGURE: self._on_configure,
            STATE_CONFIG_SUBJECT: self._on_config_subject,
            STATE_CONFIG_GRADE: self._on_config_grade,
            STATE_CONFIG_CLASS: self._on_config_class,
            STATE_CONFIG_LANGUAGE: self._on_config_language,
            STATE_CREATE: self._on_create,
            STATE_SELECT_CHAPTERS: self._on_select_chapters,
            STATE_SELECT_TOPICS: self._on_select_topics,
            STATE_REVIEW: self._on_review,
            STATE_POST_GENERATE: self._on_post_generate,
            STATE_MY_EXAMS: self._on_my_exams,
            STATE_MY_EXAM_DETAIL: self._on_my_exam_detail,
            STATE_FEEDBACK: self._on_feedback,
            STATE_HELP: self._on_help,
        }.get(session.state, self._on_main)
        handler(wa_id, raw, session, wf)
        self._persist(session, wf)

    @staticmethod
    def _profile_supported(profile: TeacherProfile) -> bool:
        return profile.grade in ALLOWED_GRADES and profile.subject in ALLOWED_SUBJECTS

    def _workflow(self, session: WhatsAppSession, profile: TeacherProfile) -> TeacherWorkflow:
        wf = self.workflow_factory(profile=profile)
        cfg = wf.get_current_config()
        if session.subject:
            try:
                wf.set_subject(session.subject)
            except ValueError:
                wf.set_subject(cfg.subject)
        try:
            wf.set_grade(session.grade)
        except ValueError:
            pass
        try:
            wf.set_class_id(session.class_id)
        except ValueError:
            pass
        try:
            wf.set_output_language(session.output_language)
        except ValueError:
            pass
        if session.selected_chapter_ids:
            try:
                wf.select_chapters(list(session.selected_chapter_ids))
            except ValueError:
                wf.reset_create_selection()
        if session.selected_chapter_ids and session.selected_topic_ids is not None:
            try:
                wf.select_topics(list(session.selected_topic_ids))
            except ValueError:
                wf.select_topics(None)
        if session.last_exam_id:
            try:
                wf.last_exam = wf.get_exam(session.last_exam_id)
            except ValueError:
                wf.last_exam = None
        return wf

    def _persist(self, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        cfg = wf.get_current_config()
        session.subject = cfg.subject
        session.grade = cfg.grade
        session.class_id = cfg.class_id
        session.output_language = cfg.output_language
        session.selected_chapter_ids = list(cfg.selected_chapter_ids)
        session.selected_topic_ids = (
            None if cfg.selected_topic_ids is None else list(cfg.selected_topic_ids)
        )
        if wf.last_exam is not None:
            session.last_exam_id = wf.last_exam.exam_id
        self.store.put(session)

    def _cancel(self, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        session.pending_subject = wf.get_current_config().subject
        session.pending_grade = wf.get_current_config().grade
        session.pending_class_id = wf.get_current_config().class_id
        session.pending_language = wf.get_current_config().output_language
        session.detail_exam_id = ""
        session.feedback_exam_id = ""

    def _go_back(self, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        if session.state == STATE_CONFIGURE:
            self._cancel(session, wf)
        session.state = PARENT_STATE.get(session.state, STATE_MAIN)

    def _show_state(self, wa_id: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        if session.state == STATE_MAIN:
            self._send_main(wa_id, wf)
        elif session.state == STATE_CONFIGURE:
            self._send_configure(wa_id, session)
        elif session.state == STATE_CREATE:
            self._send_create(wa_id, wf)
        elif session.state == STATE_REVIEW:
            self._send_review(wa_id, wf)
        elif session.state == STATE_POST_GENERATE:
            self.client.send_text(wa_id, POST_GENERATE_MENU)
        elif session.state == STATE_MY_EXAMS:
            self._send_my_exams(wa_id, wf)
        elif session.state == STATE_MY_EXAM_DETAIL:
            self._send_exam_detail(wa_id, wf, session.detail_exam_id)
        elif session.state == STATE_FEEDBACK:
            self._send_feedback(wa_id, wf, session)
        elif session.state == STATE_SELECT_CHAPTERS:
            self._send_chapters(wa_id, wf)
        elif session.state == STATE_SELECT_TOPICS:
            self._send_topics(wa_id, wf)
        else:
            self._send_main(wa_id, wf)
            session.state = STATE_MAIN

    def _reply_unknown(self, wa_id: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        self.client.send_text(wa_id, UNKNOWN_OPTION)
        self._show_state(wa_id, session, wf)

    def _on_main(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        if choice == 1:
            self._enter_configure(session, wf)
            session.state = STATE_CONFIGURE
            self._send_configure(wa_id, session)
        elif choice == 2:
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
        elif choice == 3:
            session.state = STATE_MY_EXAMS
            self._send_my_exams(wa_id, wf)
        elif choice == 4:
            session.state = STATE_FEEDBACK
            self._send_feedback(wa_id, wf, session)
        elif choice == 5:
            session.state = STATE_MAIN
            self.client.send_text(wa_id, HELP_TEXT)
        elif choice == 0:
            session.state = STATE_MAIN
            self.client.send_text(wa_id, "Exit. Send hi to start again.")
        else:
            self._reply_unknown(wa_id, session, wf)
        self._log(wa_id, session, "main_choice")

    def _on_configure(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        if choice == 1:
            session.state = STATE_CONFIG_SUBJECT
            self.client.send_text(wa_id, "SUBJECT\n\n1. Mathematics\n2. English")
        elif choice == 2:
            session.state = STATE_CONFIG_GRADE
            self.client.send_text(wa_id, "GRADE\n\n1. Grade 10")
        elif choice == 3:
            session.state = STATE_CONFIG_CLASS
            self.client.send_text(wa_id, "CLASS ID\n\nSend Class ID, for example:\n10-A")
        elif choice == 4:
            session.state = STATE_CONFIG_LANGUAGE
            self.client.send_text(wa_id, "OUTPUT LANGUAGE\n\n1. English\n2. Hindi")
        elif choice == 5:
            try:
                wf.set_subject(session.pending_subject)
                wf.set_grade(session.pending_grade)
                wf.set_class_id(session.pending_class_id)
                wf.set_output_language(session.pending_language)
            except ValueError as exc:
                self.client.send_text(wa_id, str(exc))
                self._send_configure(wa_id, session)
                return
            session.state = STATE_MAIN
            self._send_main(wa_id, wf)
        elif choice == 0:
            self._go_back(session, wf)
            self._send_main(wa_id, wf)
        else:
            self._reply_unknown(wa_id, session, wf)

    def _on_config_subject(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        if choice == 1:
            session.pending_subject = "Mathematics"
        elif choice == 2:
            session.pending_subject = "English"
        elif choice == 0:
            session.state = STATE_CONFIGURE
            self._send_configure(wa_id, session)
            return
        else:
            self.client.send_text(wa_id, "Choose 1 or 2.")
            return
        session.state = STATE_CONFIGURE
        self._send_configure(wa_id, session)

    def _on_config_grade(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        if choice in (1, 10):
            session.pending_grade = 10
            session.state = STATE_CONFIGURE
            self._send_configure(wa_id, session)
            return
        if choice == 0:
            session.state = STATE_CONFIGURE
            self._send_configure(wa_id, session)
            return
        self.client.send_text(wa_id, "Only Grade 10 is available.")

    def _on_config_class(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        if parse_menu_number(raw) == 0:
            session.state = STATE_CONFIGURE
            self._send_configure(wa_id, session)
            return
        value = normalize_text(raw)
        if not value:
            self.client.send_text(wa_id, "Class ID cannot be empty.")
            return
        session.pending_class_id = value
        session.state = STATE_CONFIGURE
        self._send_configure(wa_id, session)

    def _on_config_language(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        if choice == 1:
            session.pending_language = "English"
        elif choice == 2:
            session.pending_language = "Hindi"
        elif choice == 0:
            session.state = STATE_CONFIGURE
            self._send_configure(wa_id, session)
            return
        else:
            self.client.send_text(wa_id, "Choose 1 or 2.")
            return
        session.state = STATE_CONFIGURE
        self._send_configure(wa_id, session)

    def _on_create(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        if choice == 1:
            session.state = STATE_SELECT_CHAPTERS
            self._send_chapters(wa_id, wf)
        elif choice == 2:
            session.state = STATE_SELECT_TOPICS
            self._send_topics(wa_id, wf)
        elif choice == 3:
            session.state = STATE_REVIEW
            self._send_review(wa_id, wf)
        elif choice == 4:
            self._generate(wa_id, session, wf)
        elif choice == 0:
            session.state = STATE_MAIN
            self._send_main(wa_id, wf)
        else:
            self._reply_unknown(wa_id, session, wf)

    def _on_select_chapters(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        if parse_menu_number(raw) == 0:
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
            return
        chapters = wf.get_available_chapters()
        if not chapters:
            session.state = STATE_CREATE
            self.client.send_text(wa_id, "No chapters are available for this subject.")
            self._send_create(wa_id, wf)
            return
        try:
            indexes = parse_index_list(raw, len(chapters))
            chosen = [chapters[i - 1].chapter_id for i in indexes]
            selected = wf.select_chapters(chosen)
        except ValueError:
            self.client.send_text(wa_id, BAD_SELECTION)
            return
        lines = ["Selected:"]
        for ch in selected:
            lines.append(f"- {ch.chapter_name}")
        self.client.send_text(wa_id, "\n".join(lines))
        session.state = STATE_CREATE
        self._send_create(wa_id, wf)
        self._log(wa_id, session, "select_chapters")

    def _on_select_topics(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        if parse_menu_number(raw) == 0:
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
            return
        if not wf.get_current_config().selected_chapter_ids:
            self.client.send_text(wa_id, "Select chapters first.")
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
            return
        topics = wf.get_available_topics()
        if not topics:
            wf.select_topics(None)
            self.client.send_text(wa_id, "No topics are available for the selected chapters.")
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
            return
        try:
            if is_all(raw):
                selected = wf.select_topics(None)
            else:
                indexes = parse_index_list(raw, len(topics))
                chosen = [topics[i - 1].topic_id for i in indexes]
                selected = wf.select_topics(chosen)
        except ValueError:
            self.client.send_text(wa_id, BAD_SELECTION)
            return
        lines = ["Selected:"]
        for t in selected:
            lines.append(f"- {t.topic_name}")
        self.client.send_text(wa_id, "\n".join(lines))
        session.state = STATE_CREATE
        self._send_create(wa_id, wf)
        self._log(wa_id, session, "select_topics")

    def _on_review(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        if choice == 1:
            self._generate(wa_id, session, wf)
        elif choice == 2:
            session.state = STATE_SELECT_CHAPTERS
            self._send_chapters(wa_id, wf)
        elif choice == 3:
            session.state = STATE_SELECT_TOPICS
            self._send_topics(wa_id, wf)
        elif choice == 0:
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
        else:
            self._reply_unknown(wa_id, session, wf)

    def _on_post_generate(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        exam_id = session.last_exam_id or (wf.last_exam.exam_id if wf.last_exam else "")
        if choice == 1:
            self._send_key_document(wa_id, wf, exam_id)
            self.client.send_text(wa_id, POST_GENERATE_MENU)
        elif choice == 2:
            try:
                wf.save_exam(exam_id or None)
                self.client.send_text(wa_id, "Exam saved.")
            except ValueError as exc:
                self.client.send_text(wa_id, str(exc))
            self.client.send_text(wa_id, POST_GENERATE_MENU)
        elif choice == 3:
            self._submit(wa_id, wf, exam_id)
            self.client.send_text(wa_id, POST_GENERATE_MENU)
        elif choice == 4:
            wf.reset_create_selection()
            session.last_exam_id = ""
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
        elif choice == 0:
            session.state = STATE_MAIN
            self._send_main(wa_id, wf)
        else:
            self._reply_unknown(wa_id, session, wf)

    def _on_my_exams(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        if parse_menu_number(raw) == 0:
            session.state = STATE_MAIN
            self._send_main(wa_id, wf)
            return
        exams = wf.list_my_exams()
        choice = parse_menu_number(raw)
        if choice is None or choice < 1 or choice > len(exams):
            self._reply_unknown(wa_id, session, wf)
            return
        session.detail_exam_id = exams[choice - 1].exam_id
        session.state = STATE_MY_EXAM_DETAIL
        self._send_exam_detail(wa_id, wf, session.detail_exam_id)

    def _on_my_exam_detail(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        choice = parse_menu_number(raw)
        exam_id = session.detail_exam_id
        try:
            rec = wf.get_exam(exam_id)
        except ValueError:
            session.state = STATE_MY_EXAMS
            self.client.send_text(wa_id, "Exam not found.")
            self._send_my_exams(wa_id, wf)
            return
        if choice == 1:
            self._send_exam_document(wa_id, wf, exam_id)
            self._send_exam_detail(wa_id, wf, exam_id)
        elif choice == 2:
            self._send_key_document(wa_id, wf, exam_id)
            self._send_exam_detail(wa_id, wf, exam_id)
        elif choice == 3 and rec.status == STATUS_DRAFT:
            self._submit(wa_id, wf, exam_id)
            self._send_exam_detail(wa_id, wf, exam_id)
        elif choice == 0:
            session.state = STATE_MY_EXAMS
            self._send_my_exams(wa_id, wf)
        else:
            self._reply_unknown(wa_id, session, wf)

    def _on_feedback(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        items = wf.list_feedback()
        choice = parse_menu_number(raw)
        if choice == 0:
            session.feedback_exam_id = ""
            session.state = STATE_MAIN
            self._send_main(wa_id, wf)
            return
        if session.feedback_exam_id:
            if choice == 1:
                self._send_exam_document(wa_id, wf, session.feedback_exam_id)
                self._send_feedback_detail(wa_id, wf, session.feedback_exam_id)
                return
            self._reply_unknown(wa_id, session, wf)
            return
        if choice is None or choice < 1 or choice > len(items):
            self._reply_unknown(wa_id, session, wf)
            return
        session.feedback_exam_id = items[choice - 1].exam_id
        self._send_feedback_detail(wa_id, wf, session.feedback_exam_id)

    def _on_help(self, wa_id: str, raw: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        session.state = STATE_MAIN
        if parse_menu_number(raw) == 0:
            self._send_main(wa_id, wf)
            return
        self._on_main(wa_id, raw, session, wf)

    def _enter_configure(self, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        cfg = wf.get_current_config()
        session.pending_subject = cfg.subject
        session.pending_grade = cfg.grade
        session.pending_class_id = cfg.class_id
        session.pending_language = cfg.output_language

    def _generate(self, wa_id: str, session: WhatsAppSession, wf: TeacherWorkflow) -> None:
        self.client.send_text(wa_id, "Creating your exam. This may take a little time...")
        try:
            record = wf.generate_exam()
        except ValueError as exc:
            self.client.send_text(wa_id, f"Could not create the exam. {exc}")
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
            self._log(wa_id, session, "generate", success=False)
            return
        except Exception:
            log.exception(
                "generate failed wa_id=%s state=%s",
                mask_wa_id(wa_id),
                session.state,
            )
            self.client.send_text(wa_id, "Could not create the exam. Please try again or send MENU.")
            session.state = STATE_CREATE
            self._send_create(wa_id, wf)
            self._log(wa_id, session, "generate", success=False)
            return
        session.last_exam_id = record.exam_id
        session.state = STATE_POST_GENERATE
        self.client.send_text(wa_id, f"EXAM CREATED ✓\nExam ID: {record.exam_id}")
        self._send_exam_document(wa_id, wf, record.exam_id, filename=self._exam_filename(record))
        self.client.send_text(wa_id, POST_GENERATE_MENU)
        self._log(wa_id, session, "generate", exam_id=record.exam_id, success=True)

    def _submit(self, wa_id: str, wf: TeacherWorkflow, exam_id: str) -> None:
        try:
            wf.submit_exam(exam_id or None)
            self.client.send_text(wa_id, "Exam submitted to Principal. ✓")
            self._log(wa_id, None, "submit", exam_id=exam_id, success=True)
        except ValueError as exc:
            self.client.send_text(wa_id, str(exc))
            self._log(wa_id, None, "submit", exam_id=exam_id, success=False)

    def _send_exam_document(
        self,
        wa_id: str,
        wf: TeacherWorkflow,
        exam_id: str,
        filename: str | None = None,
    ) -> None:
        try:
            content = wf.exam_pdf_bytes(exam_id or None)
        except ValueError as exc:
            self.client.send_text(wa_id, str(exc))
            return
        if not content:
            log.error("exam pdf missing exam_id=%s", exam_id)
            self.client.send_text(wa_id, "The exam PDF is not available yet.")
            return
        rec = wf.get_exam(exam_id) if exam_id else wf.last_exam
        name = filename or (self._exam_filename(rec) if rec else "exam.pdf")
        self.client.send_document_bytes(wa_id, content, filename=name)

    def _send_key_document(self, wa_id: str, wf: TeacherWorkflow, exam_id: str) -> None:
        try:
            content = wf.answer_key_pdf_bytes(exam_id or None)
        except ValueError as exc:
            self.client.send_text(wa_id, str(exc))
            return
        if not content:
            log.error("answer key pdf missing exam_id=%s", exam_id)
            self.client.send_text(wa_id, "The answer key is not available yet.")
            return
        rec = wf.get_exam(exam_id) if exam_id else wf.last_exam
        name = self._key_filename(rec) if rec else "answer_key.pdf"
        self.client.send_document_bytes(wa_id, content, filename=name)

    def _send_main(self, wa_id: str, wf: TeacherWorkflow) -> None:
        cfg = wf.get_current_config()
        profile = wf.get_teacher_profile()
        name = cfg.teacher_name or getattr(profile, "teacher_name", "Teacher")
        text = (
            "TEACHER EXAM(Release 1)\n"
            "\n"
            f"Welcome, {name}\n"
            "\n"
            "Current:\n"
            f"Grade {cfg.grade} | {cfg.subject} | Class {cfg.class_id} | {cfg.output_language}\n"
            "\n"
            "1. Configure Exam\n"
            "2. Create Exam\n"
            "3. My Exams\n"
            "4. Principal Feedback\n"
            "5. Help\n"
            "0. Exit"
        )
        self.client.send_text(wa_id, text)

    def _send_configure(self, wa_id: str, session: WhatsAppSession) -> None:
        text = (
            "CONFIGURE EXAM\n"
            "\n"
            "Current:\n"
            f"Subject: {session.pending_subject}\n"
            f"Grade: {session.pending_grade}\n"
            f"Class ID: {session.pending_class_id}\n"
            f"Output Language: {session.pending_language}\n"
            "\n"
            "1. Subject\n"
            "2. Grade\n"
            "3. Class ID\n"
            "4. Output Language\n"
            "5. Save & Return\n"
            "0. Back"
        )
        self.client.send_text(wa_id, text)

    def _send_create(self, wa_id: str, wf: TeacherWorkflow) -> None:
        cfg = wf.get_current_config()
        text = (
            "CREATE EXAM\n"
            "\n"
            f"Subject: {cfg.subject}\n"
            f"Grade: {cfg.grade}\n"
            f"Class: {cfg.class_id}\n"
            f"Output: {cfg.output_language}\n"
            "\n"
            "1. Select Chapters\n"
            "2. Select Topics\n"
            "3. Review Selection\n"
            "4. Generate Exam\n"
            "0. Back"
        )
        self.client.send_text(wa_id, text)

    def _send_chapters(self, wa_id: str, wf: TeacherWorkflow) -> None:
        chapters = wf.get_available_chapters()
        lines = ["SELECT CHAPTERS", ""]
        if not chapters:
            lines.append("No chapters are available for this subject.")
        else:
            for i, ch in enumerate(chapters, start=1):
                lines.append(f"{i}. {ch.chapter_name}")
            lines.append("")
            lines.append("Reply:")
            lines.append("1,2")
            lines.append("or ALL")
        self.client.send_text(wa_id, "\n".join(lines))

    def _send_topics(self, wa_id: str, wf: TeacherWorkflow) -> None:
        if not wf.get_current_config().selected_chapter_ids:
            self.client.send_text(wa_id, "Select chapters first.")
            return
        topics = wf.get_available_topics()
        lines = ["SELECT TOPICS", ""]
        if not topics:
            lines.append("No topics are available for the selected chapters.")
        else:
            current_chapter = None
            for i, t in enumerate(topics, start=1):
                if t.chapter_name != current_chapter:
                    current_chapter = t.chapter_name
                    lines.append(current_chapter)
                lines.append(f"{i}. {t.topic_name}")
            lines.append("")
            lines.append("Reply:")
            lines.append("1,3,4")
            lines.append("or ALL")
        self.client.send_text(wa_id, "\n".join(lines))

    def _send_review(self, wa_id: str, wf: TeacherWorkflow) -> None:
        try:
            review = wf.review_configuration()
        except Exception as exc:
            self.client.send_text(wa_id, str(exc))
            return
        lines = [
            "REVIEW EXAM",
            "",
            f"Teacher: {review['teacher_name']}",
            f"Grade: {review['grade']}",
            f"Subject: {review['subject']}",
            f"Class: {review['class_id']}",
            f"Output Language: {review['output_language']}",
            "",
            "Chapters:",
        ]
        if review["selected_chapters"]:
            lines.extend(f"- {name}" for name in review["selected_chapters"])
        else:
            lines.append("- (none)")
        lines.append("")
        lines.append("Topics:")
        if review["selected_topics"]:
            lines.extend(f"- {name}" for name in review["selected_topics"])
        else:
            lines.append("- (none)")
        lines.extend(
            [
                "",
                f"Question Source: {review['question_source']}",
                "",
                "1. Generate Exam",
                "2. Change Chapters",
                "3. Change Topics",
                "0. Back",
            ]
        )
        self.client.send_text(wa_id, "\n".join(lines))

    def _send_my_exams(self, wa_id: str, wf: TeacherWorkflow) -> None:
        exams = wf.list_my_exams()
        lines = ["MY EXAMS", ""]
        if not exams:
            lines.append("No saved exams yet.")
        else:
            for i, rec in enumerate(exams, start=1):
                lines.append(f"{i}. {self._format_date(rec.created_at)} | {rec.subject} | {rec.status}")
            lines.append("")
            lines.append("Reply with exam number, or 0 to go back.")
        lines.append("")
        lines.append("0. Back")
        self.client.send_text(wa_id, "\n".join(lines))

    def _send_exam_detail(self, wa_id: str, wf: TeacherWorkflow, exam_id: str) -> None:
        try:
            rec = wf.get_exam(exam_id)
        except ValueError:
            self.client.send_text(wa_id, "Exam not found.")
            return
        lines = [
            "EXAM DETAILS",
            "",
            f"Subject: {rec.subject}",
            f"Grade: {rec.grade}",
            f"Class: {rec.class_id}",
            f"Status: {self._status_label(rec.status)}",
            "",
            "1. Send Exam PDF",
            "2. Send Answer Key",
        ]
        if rec.status == STATUS_DRAFT:
            lines.append("3. Submit to Principal")
        lines.append("0. Back")
        self.client.send_text(wa_id, "\n".join(lines))

    def _send_feedback(self, wa_id: str, wf: TeacherWorkflow, session: WhatsAppSession) -> None:
        items = wf.list_feedback()
        session.feedback_exam_id = ""
        if not items:
            self.client.send_text(wa_id, "No Principal feedback yet.")
            return
        if len(items) == 1:
            session.feedback_exam_id = items[0].exam_id
            self._send_feedback_detail(wa_id, wf, items[0].exam_id)
            return
        lines = ["PRINCIPAL FEEDBACK", ""]
        for i, rec in enumerate(items, start=1):
            lines.append(f"{i}. {rec.subject} | {self._status_label(rec.status)}")
        lines.extend(["", "Reply with a number, or 0 to go back."])
        self.client.send_text(wa_id, "\n".join(lines))

    def _send_feedback_detail(self, wa_id: str, wf: TeacherWorkflow, exam_id: str) -> None:
        try:
            rec = wf.get_exam(exam_id)
        except ValueError:
            self.client.send_text(wa_id, "No Principal feedback yet.")
            return
        text = (
            "PRINCIPAL FEEDBACK\n"
            "\n"
            f"{rec.subject}\n"
            f"Status: {self._status_label(rec.status)}\n"
            "\n"
            "Feedback:\n"
            f"{rec.principal_feedback or '(none)'}\n"
            "\n"
            "1. Send Exam PDF\n"
            "0. Back"
        )
        self.client.send_text(wa_id, text)

    def _exam_filename(self, record) -> str:
        subj = "Math" if str(record.subject).lower().startswith("math") else "English"
        class_id = str(record.class_id or "class").replace(" ", "")
        exam_id = str(record.exam_id or "exam").replace(" ", "_")
        return f"Grade{record.grade}_{subj}_{class_id}_{exam_id}.pdf"

    def _key_filename(self, record) -> str:
        return self._exam_filename(record).replace(".pdf", "_AnswerKey.pdf")

    def _format_date(self, created_at: str) -> str:
        try:
            return datetime.fromisoformat(created_at).strftime("%b %d")
        except Exception:
            return (created_at or "")[:10]

    def _status_label(self, status: str) -> str:
        return (status or "").replace("_", " ")

    def _log(
        self,
        wa_id: str,
        session: WhatsAppSession | None,
        action: str,
        exam_id: str = "",
        success: bool = True,
    ) -> None:
        log.info(
            "wa_id=%s state=%s action=%s exam_id=%s success=%s",
            mask_wa_id(wa_id),
            session.state if session else "",
            action,
            exam_id,
            success,
        )
