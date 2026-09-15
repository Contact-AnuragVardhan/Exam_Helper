from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import tempfile

from services.logger import get_logger
from services.paths import load_json, sample_data_dir, source_path
from services.pipeline import run_exam

from .models import (
    ALLOWED_GRADES,
    ALLOWED_OUTPUT_LANGUAGES,
    ALLOWED_SUBJECTS,
    ChapterChoice,
    ExamRecord,
    SessionConfig,
    STATUS_DRAFT,
    STATUS_SUBMITTED,
    TeacherProfile,
    TopicChoice,
    normalize_output_language,
)
from .storage import (
    get_answer_key_pdf_bytes,
    get_exam_docx_bytes,
    get_exam_pdf_bytes,
    get_exam_record,
    list_feedback_exams,
    list_teacher_exams,
    load_teacher_profile,
    materialize_exam_docx,
    materialize_exam_pdf,
    upsert_exam_record,
)


log = get_logger("teacher_workflow")


class TeacherWorkflow:
    """Thin orchestration layer. Calls the existing frozen exam engines."""

    def __init__(self, profile: TeacherProfile | None = None) -> None:
        self.profile: TeacherProfile = profile or load_teacher_profile()
        self.session: SessionConfig = SessionConfig.from_profile(self.profile)
        self.last_exam: ExamRecord | None = None

    def get_teacher_profile(self) -> TeacherProfile:
        return self.profile

    def get_current_config(self) -> SessionConfig:
        return self.session

    def set_subject(self, subject: str) -> str:
        raw = (subject or "").strip()
        low = raw.lower()
        if low.startswith("eng"):
            chosen = "English"
        elif low.startswith("math"):
            chosen = "Mathematics"
        else:
            raise ValueError("Subject must be Mathematics or English.")
        if chosen not in ALLOWED_SUBJECTS:
            raise ValueError("Subject must be Mathematics or English.")
        if chosen != self.session.subject:
            self.session.subject = chosen
            self._clear_selection()
        return self.session.subject

    def set_grade(self, grade: int | str) -> int:
        value = int(grade)
        if value not in ALLOWED_GRADES:
            raise ValueError("Only Grade 10 is available.")
        self.session.grade = value
        return self.session.grade

    def set_class_id(self, class_id: str) -> str:
        value = (class_id or "").strip()
        if not value:
            raise ValueError("Class ID cannot be empty.")
        self.session.class_id = value
        return self.session.class_id

    def set_output_language(self, language: str) -> str:
        chosen = normalize_output_language(language)
        if chosen not in ALLOWED_OUTPUT_LANGUAGES:
            raise ValueError("Output language must be English or Hindi.")
        self.session.output_language = chosen
        return self.session.output_language

    def _clear_selection(self) -> None:
        self.session.selected_chapter_ids = []
        self.session.selected_topic_ids = None

    def reset_create_selection(self) -> None:
        self._clear_selection()
        self.last_exam = None

    def get_available_chapters(self) -> list[ChapterChoice]:
        subject = self.session.subject
        if subject == "English":
            return self._english_chapters()
        return self._math_chapters()

    def _math_chapters(self) -> list[ChapterChoice]:
        from services.book_importer import load_book_index

        index = load_book_index()
        out: list[ChapterChoice] = []
        for c in index.get("chapters") or []:
            out.append(
                ChapterChoice(
                    chapter_id=c["chapter_id"],
                    chapter_number=int(c.get("chapter_number") or 0),
                    chapter_name=c.get("chapter_name") or c["chapter_id"],
                )
            )
        return out

    def _english_chapters(self) -> list[ChapterChoice]:
        from services.english_book_importer import load_english_book_index
        from services.english_syllabus import item_allowed, load_active_english_syllabus

        index = load_english_book_index()
        syllabus = load_active_english_syllabus()
        out: list[ChapterChoice] = []
        for c in index.get("chapters") or []:
            name = c.get("chapter_name") or ""
            if not item_allowed(name, syllabus):
                continue
            out.append(
                ChapterChoice(
                    chapter_id=c["chapter_id"],
                    chapter_number=int(c.get("chapter_number") or 0),
                    chapter_name=name,
                    kind=str(c.get("kind") or ""),
                )
            )
        return out

    def select_chapters(self, chapter_ids: list[str]) -> list[ChapterChoice]:
        available = {c.chapter_id: c for c in self.get_available_chapters()}
        if not chapter_ids:
            raise ValueError("Select at least one chapter.")
        unknown = [cid for cid in chapter_ids if cid not in available]
        if unknown:
            raise ValueError("One or more chapters are not available for this subject.")
        self.session.selected_chapter_ids = [cid for cid in chapter_ids if cid in available]
        self.session.selected_topic_ids = None
        return self.selected_chapters()

    def selected_chapters(self) -> list[ChapterChoice]:
        available = {c.chapter_id: c for c in self.get_available_chapters()}
        return [available[cid] for cid in self.session.selected_chapter_ids if cid in available]

    def get_available_topics(self) -> list[TopicChoice]:
        chapters = self.selected_chapters()
        if not chapters:
            return []
        wanted = {c.chapter_id: c for c in chapters}
        if self.session.subject == "English":
            from services.english_book_importer import load_english_book_index

            topics = load_english_book_index().get("topics") or []
        else:
            from services.book_importer import load_book_index

            topics = load_book_index().get("topics") or []
        out: list[TopicChoice] = []
        for t in topics:
            cid = t.get("chapter_id")
            if cid not in wanted:
                continue
            out.append(
                TopicChoice(
                    topic_id=t["topic_id"],
                    chapter_id=cid,
                    chapter_name=wanted[cid].chapter_name,
                    topic_name=t.get("topic_name") or t["topic_id"],
                    section_number=str(t.get("section_number") or ""),
                )
            )
        return out

    def select_topics(self, topic_ids: list[str] | None) -> list[TopicChoice]:
        available = {t.topic_id: t for t in self.get_available_topics()}
        if topic_ids is None:
            self.session.selected_topic_ids = None
            return list(available.values())
        unknown = [tid for tid in topic_ids if tid not in available]
        if unknown:
            raise ValueError("Topics must belong to the selected chapters.")
        self.session.selected_topic_ids = [tid for tid in topic_ids if tid in available]
        return [available[tid] for tid in self.session.selected_topic_ids]

    def selected_topics(self) -> list[TopicChoice]:
        available = {t.topic_id: t for t in self.get_available_topics()}
        if self.session.selected_topic_ids is None:
            return list(available.values())
        return [available[tid] for tid in self.session.selected_topic_ids if tid in available]

    def review_configuration(self) -> dict:
        cfg = self.session
        chapters = self.selected_chapters()
        topics = self.selected_topics()
        profile = self._exam_profile()
        source = (profile.get("question_source_default") or "BOOK").upper()
        return {
            "teacher_name": cfg.teacher_name,
            "grade": cfg.grade,
            "subject": cfg.subject,
            "class_id": cfg.class_id,
            "output_language": cfg.output_language,
            "selected_chapters": [c.chapter_name for c in chapters],
            "selected_topics": [t.topic_name for t in topics],
            "question_source": source,
            "exam_profile": self._exam_profile_label(profile),
            "topics_are_all": self.session.selected_topic_ids is None,
        }

    def _exam_profile(self) -> dict:
        from services.blueprint_builder import load_profile

        subject = "english" if self.session.subject == "English" else None
        return load_profile(subject)

    def _exam_profile_label(self, profile: dict) -> str:
        subject = profile.get("subject") or self.session.subject
        grade = profile.get("grade") or self.session.grade
        return f"Grade {grade} {subject}"

    def validate_for_generate(self) -> None:
        if self.session.grade not in ALLOWED_GRADES:
            raise ValueError("Grade is required.")
        if self.session.subject not in ALLOWED_SUBJECTS:
            raise ValueError("Subject is required.")
        if not self.session.selected_chapter_ids:
            raise ValueError("Select at least one chapter.")
        topics = self.selected_topics()
        chapter_ids = set(self.session.selected_chapter_ids)
        if self.session.selected_topic_ids:
            if not topics:
                raise ValueError("Selected topics are not valid for the selected chapters.")
            for t in topics:
                if t.chapter_id not in chapter_ids:
                    raise ValueError("Topics must belong to the selected chapters.")

    def build_exam_config(self) -> dict:
        """Exact config object expected by the existing frozen generator."""
        self.validate_for_generate()
        if self.session.subject == "English":
            return self._english_exam_config()
        return self._math_exam_config()

    def _math_exam_config(self) -> dict:
        chapters = self.selected_chapters()
        topic_ids = None
        if self.session.selected_topic_ids is not None:
            topic_ids = list(self.session.selected_topic_ids)
        return {
            "exam_name": "Grade 10 Mathematics Quarterly Pilot",
            "grade": 10,
            "subject": "Mathematics",
            "exam_type": "Quarterly",
            "total_marks": 75,
            "duration_minutes": 180,
            "allowed_chapter_numbers": [c.chapter_number for c in chapters],
            "allowed_topic_ids": topic_ids,
            "excluded_question_ids": [],
            "difficulty": "default",
            "question_source": "BOOK",
            "book_percent": 100,
            "new_percent": 0,
            "output_language": self.session.output_language,
        }

    def _english_exam_config(self) -> dict:
        cfg = {
            "exam_name": "Grade 10 English Quarterly",
            "grade": 10,
            "subject": "English",
            "exam_type": "Quarterly",
            "total_marks": 80,
            "duration_minutes": 180,
            "book": "First Flight",
            "syllabus": "Q1 / Quarterly",
            "difficulty": "default",
            "question_source": "MIXED",
            "book_percent": 70,
            "new_percent": 30,
            "output_language": self.session.output_language,
        }
        if not self._english_uses_full_allowed_set():
            cfg["syllabus_file"] = str(self._write_english_session_syllabus())
        return cfg

    def _english_uses_full_allowed_set(self) -> bool:
        available_ch = [c.chapter_id for c in self.get_available_chapters()]
        selected_ch = list(self.session.selected_chapter_ids)
        if sorted(available_ch) != sorted(selected_ch):
            return False
        if self.session.selected_topic_ids is None:
            return True
        available_topics = [t.topic_id for t in self.get_available_topics()]
        return sorted(available_topics) == sorted(self.session.selected_topic_ids)

    def _write_english_session_syllabus(self) -> Path:
        """Use the existing syllabus_file hook. Does not change the English engine."""
        chapters = self.selected_chapters()
        prose = [c.chapter_name for c in chapters if (c.kind or "").lower() != "poem"]
        poems = [c.chapter_name for c in chapters if (c.kind or "").lower() == "poem"]
        lines = [
            "Book First Flight - Grade 10",
            "",
            "Chapters:",
        ]
        lines.extend(prose)
        lines.append("")
        lines.append("Topics Explicitly selected:")
        for poem in poems:
            lines.append(f"Poem Study: {poem}")
        runtime_dir = Path(tempfile.gettempdir()) / "exam_helper" / "session" / self.session.teacher_id
        runtime_dir.mkdir(parents=True, exist_ok=True)
        path = runtime_dir / "session_english_syllabus.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def generate_exam(self) -> ExamRecord:
        exam_config = self.build_exam_config()
        log.info(
            "Teacher generate subject=%s chapters=%s topics=%s",
            exam_config.get("subject"),
            self.session.selected_chapter_ids,
            self.session.selected_topic_ids,
        )
        self._reuse_imported_sample_if_source_missing()
        result = run_exam(exam_config)
        exam_id = result["exam_id"]
        out_dir = Path(result["output_dir"])
        exam_pdf = out_dir / "exam.pdf"
        exam_docx = out_dir / "exam.docx"
        key_pdf = out_dir / "answer_key.pdf"
        record = ExamRecord(
            exam_id=exam_id,
            teacher_id=self.session.teacher_id,
            teacher_name=self.session.teacher_name,
            grade=self.session.grade,
            subject=self.session.subject,
            class_id=self.session.class_id,
            output_language=self.session.output_language,
            selected_chapters=[c.chapter_name for c in self.selected_chapters()],
            selected_topics=[t.topic_name for t in self.selected_topics()],
            exam_pdf_path=f"db://exam_helper_exams/{exam_id}/exam.pdf",
            answer_key_pdf_path=f"db://exam_helper_exams/{exam_id}/answer_key.pdf",
            created_at=datetime.now().isoformat(timespec="seconds"),
            status=STATUS_DRAFT,
            principal_feedback="",
            output_dir=f"db://exam_helper_exams/{exam_id}",
        )
        artifacts = {
            "exam_config": exam_config,
            "exam_json": result.get("exam") or {},
            "blueprint_json": result.get("blueprint") or {},
            "validation_json": result.get("report") or {},
            "llm_usage_json": result.get("usage") or {},
            "allowed_content_json": result.get("allowed") or {},
            "exam_text": (out_dir / "exam.txt").read_text(encoding="utf-8") if (out_dir / "exam.txt").exists() else "",
            "answer_key_text": (out_dir / "answer_key.txt").read_text(encoding="utf-8") if (out_dir / "answer_key.txt").exists() else "",
            "validation_text": (out_dir / "validation_report.txt").read_text(encoding="utf-8") if (out_dir / "validation_report.txt").exists() else "",
            "exam_pdf": exam_pdf.read_bytes() if exam_pdf.exists() else b"",
            "exam_docx": exam_docx.read_bytes() if exam_docx.exists() else b"",
            "answer_key_pdf": key_pdf.read_bytes() if key_pdf.exists() else b"",
        }
        upsert_exam_record(record, artifacts=artifacts)
        log.info(
            "Exam persisted exam_id=%s teacher_id=%s status=%s",
            record.exam_id,
            record.teacher_id,
            record.status,
        )
        # Generated files are only a transient build workspace. The durable copy is in PostgreSQL.
        shutil.rmtree(out_dir, ignore_errors=True)
        self.last_exam = record
        return record

    def save_exam(self, exam_id: str | None = None) -> ExamRecord:
        record = self._require_exam(exam_id)
        upsert_exam_record(record)
        log.info("Exam saved exam_id=%s teacher_id=%s", record.exam_id, record.teacher_id)
        return record

    def submit_exam(self, exam_id: str | None = None) -> ExamRecord:
        record = self._require_exam(exam_id)
        if record.status != STATUS_DRAFT:
            raise ValueError("Only a DRAFT exam can be submitted.")
        record.status = STATUS_SUBMITTED
        upsert_exam_record(record)
        log.info("Exam submitted exam_id=%s teacher_id=%s", record.exam_id, record.teacher_id)
        if self.last_exam and self.last_exam.exam_id == record.exam_id:
            self.last_exam = record
        return record

    def list_my_exams(self) -> list[ExamRecord]:
        return list_teacher_exams(self.session.teacher_id)

    def get_exam(self, exam_id: str) -> ExamRecord:
        record = get_exam_record(exam_id)
        if record is None:
            raise ValueError("Exam not found.")
        return record

    def list_feedback(self) -> list[ExamRecord]:
        return list_feedback_exams(self.session.teacher_id)

    def exam_pdf_bytes(self, exam_id: str | None = None) -> bytes:
        record = self._require_exam(exam_id)
        return get_exam_pdf_bytes(record.exam_id)

    def exam_docx_bytes(self, exam_id: str | None = None) -> bytes:
        record = self._require_exam(exam_id)
        return get_exam_docx_bytes(record.exam_id)

    def answer_key_pdf_bytes(self, exam_id: str | None = None) -> bytes:
        record = self._require_exam(exam_id)
        return get_answer_key_pdf_bytes(record.exam_id)

    def exam_pdf_path(self, exam_id: str | None = None) -> Path:
        record = self._require_exam(exam_id)
        return materialize_exam_pdf(record.exam_id, answer_key=False)

    def exam_docx_path(self, exam_id: str | None = None) -> Path:
        record = self._require_exam(exam_id)
        return materialize_exam_docx(record.exam_id)

    def answer_key_pdf_path(self, exam_id: str | None = None) -> Path:
        record = self._require_exam(exam_id)
        return materialize_exam_pdf(record.exam_id, answer_key=True)

    def _reuse_imported_sample_if_source_missing(self) -> None:
        """Teacher launch/generate must not require missing Step-1 source files.

        Book/sample indexes are already imported in this copy. The frozen
        sample importer still expects the original DOCX. Reuse the existing
        index instead of changing that importer.
        """
        source = source_path("sample_exam_docx")
        existing = sample_data_dir() / "grade10_math_2026_sample.json"
        if source.exists() or not existing.exists():
            return
        import services.pipeline as pipeline

        if getattr(pipeline.import_sample_exam, "_teacher_reuse_imported", False):
            return

        def _reuse_imported_sample() -> dict:
            log.info("Sample source missing; using already imported sample index")
            return load_json(existing)

        _reuse_imported_sample._teacher_reuse_imported = True
        pipeline.import_sample_exam = _reuse_imported_sample

    def _require_exam(self, exam_id: str | None) -> ExamRecord:
        if exam_id:
            return self.get_exam(exam_id)
        if self.last_exam is not None:
            stored = get_exam_record(self.last_exam.exam_id)
            return stored or self.last_exam
        raise ValueError("No exam is available.")
