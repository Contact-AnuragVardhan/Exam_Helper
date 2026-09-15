from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from teacher_workflow.models import STATUS_DRAFT
from teacher_workflow.service import TeacherWorkflow


def _banner(title: str) -> None:
    print()
    print("----------------------------------------")
    print(title)
    print("----------------------------------------")


def _ask(prompt: str = "Choice") -> str:
    return input(f"{prompt}: ").strip()


def _open_path(path: Path) -> None:
    path = Path(path)
    print(f"Path: {path}")
    if not path.exists():
        print("File not found.")
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception as e:
        print(f"Could not open automatically ({e}). Use the path above.")


def _format_date(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at)
        return dt.strftime("%b %d")
    except Exception:
        return created_at[:10] if created_at else ""


def _status_label(status: str) -> str:
    return (status or "").replace("_", " ")


def parse_index_list(raw: str, count: int, empty_means_all: bool = False) -> list[int] | None:
    text = (raw or "").strip()
    if not text:
        return list(range(1, count + 1)) if empty_means_all else None
    if text.upper() == "ALL":
        return list(range(1, count + 1))
    nums: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        nums.append(int(part))
    for n in nums:
        if n < 1 or n > count:
            raise ValueError(f"Enter numbers from 1 to {count}, or ALL.")
    if not nums:
        raise ValueError(f"Enter numbers from 1 to {count}, or ALL.")
    return nums


def configure_exam(wf: TeacherWorkflow) -> None:
    snap = wf.get_current_config()
    subject = snap.subject
    grade = snap.grade
    class_id = snap.class_id
    output_language = snap.output_language
    while True:
        _banner("CONFIGURE EXAM")
        print()
        print("Current:")
        print(f"Subject: {subject}")
        print(f"Grade: {grade}")
        print(f"Class ID: {class_id}")
        print(f"Output Language: {output_language}")
        print()
        print("1. Subject")
        print("2. Grade")
        print("3. Class ID")
        print("4. Output Language")
        print("5. Save & Return")
        print("0. Cancel")
        print()
        choice = _ask()
        if choice == "1":
            print()
            print("1. Mathematics")
            print("2. English")
            print()
            sub = _ask("Subject")
            if sub == "1":
                subject = "Mathematics"
            elif sub == "2":
                subject = "English"
            else:
                print("Choose 1 or 2.")
        elif choice == "2":
            print()
            print("1. Grade 10")
            print()
            g = _ask("Grade")
            if g in ("1", "10"):
                grade = 10
            else:
                print("Only Grade 10 is available.")
        elif choice == "3":
            entered = input("Class ID: ").strip()
            if entered:
                class_id = entered
            else:
                print("Class ID cannot be empty.")
        elif choice == "4":
            chosen = _choose_output_language()
            if chosen:
                output_language = chosen
        elif choice == "5":
            wf.set_subject(subject)
            wf.set_grade(grade)
            wf.set_class_id(class_id)
            wf.set_output_language(output_language)
            return
        elif choice == "0":
            return
        else:
            print("Unknown option.")


def _choose_output_language() -> str | None:
    _banner("OUTPUT LANGUAGE")
    print()
    print("1. English")
    print("2. Hindi")
    print("0. Back")
    print()
    choice = _ask()
    if choice == "1":
        return "English"
    if choice == "2":
        return "Hindi"
    if choice == "0":
        return None
    print("Choose 1 or 2.")
    return None


def select_chapters_ui(wf: TeacherWorkflow) -> None:
    chapters = wf.get_available_chapters()
    _banner("SELECT CHAPTERS")
    print()
    if not chapters:
        print("No chapters are available for this subject.")
        return
    for i, ch in enumerate(chapters, start=1):
        print(f"{i}. {ch.chapter_name}")
    print()
    print("Enter numbers (e.g. 1,2,4) or ALL")
    print("0. Back")
    print()
    raw = _ask("Chapters")
    if raw == "0":
        return
    try:
        indexes = parse_index_list(raw, len(chapters), empty_means_all=False)
        if not indexes:
            print("No chapters selected.")
            return
        chosen = [chapters[i - 1].chapter_id for i in indexes]
        selected = wf.select_chapters(chosen)
        print()
        print("Selected chapters:")
        for ch in selected:
            print(f"- {ch.chapter_name}")
    except Exception as e:
        print(f"{e}")


def select_topics_ui(wf: TeacherWorkflow) -> None:
    if not wf.get_current_config().selected_chapter_ids:
        print("Select chapters first.")
        return
    topics = wf.get_available_topics()
    _banner("SELECT TOPICS")
    print()
    if not topics:
        print("No topics are available for the selected chapters.")
        wf.select_topics(None)
        return
    current_chapter = None
    for i, t in enumerate(topics, start=1):
        if t.chapter_name != current_chapter:
            current_chapter = t.chapter_name
            print(f"{current_chapter}")
        print(f"  {i}. {t.topic_name}")
    print()
    print("Enter numbers, ALL, or press Enter for ALL topics")
    print("0. Back")
    print()
    raw = _ask("Topics")
    if raw == "0":
        return
    try:
        if not raw.strip() or raw.strip().upper() == "ALL":
            selected = wf.select_topics(None)
        else:
            indexes = parse_index_list(raw, len(topics), empty_means_all=True)
            chosen = [topics[i - 1].topic_id for i in (indexes or [])]
            selected = wf.select_topics(chosen)
        print()
        print("Selected topics:")
        for t in selected:
            print(f"- {t.topic_name}")
    except Exception as e:
        print(f"{e}")


def review_selection_ui(wf: TeacherWorkflow) -> str | None:
    try:
        review = wf.review_configuration()
    except Exception as e:
        print(f"{e}")
        return None
    _banner("REVIEW EXAM CONFIGURATION")
    print()
    print(f"Teacher: {review['teacher_name']}")
    print(f"Grade: {review['grade']}")
    print(f"Subject: {review['subject']}")
    print(f"Class: {review['class_id']}")
    print(f"Output Language: {review['output_language']}")
    print()
    print("Selected Chapters:")
    if review["selected_chapters"]:
        for name in review["selected_chapters"]:
            print(f"- {name}")
    else:
        print("- (none)")
    print()
    print(f"Question Source: {review['question_source']}")
    print(f"Existing Exam Profile: {review['exam_profile']}")
    print()
    print("1. Generate Exam")
    print("2. Change Chapters")
    print("3. Change Topics")
    print("0. Back")
    print()
    return _ask()


def generate_exam_ui(wf: TeacherWorkflow) -> bool:
    try:
        wf.validate_for_generate()
    except Exception as e:
        print(f"{e}")
        return False
    print()
    print("Creating exam...")
    print("Generating questions...")
    try:
        wf.generate_exam()
    except Exception as e:
        print(f"Could not create the exam: {e}")
        return False
    print("Validating...")
    print("Creating PDF and Word document...")
    print("Done.")
    return True


def exam_created_menu(wf: TeacherWorkflow) -> str:
    rec = wf.last_exam
    if rec is None:
        print("No exam was created.")
        return "main"
    while True:
        _banner("EXAM CREATED")
        print()
        print(f"Exam ID: {rec.exam_id}")
        print(f"Subject: {rec.subject}")
        print(f"Grade: {rec.grade}")
        print(f"Class: {rec.class_id}")
        print()
        print("1. View Exam PDF")
        print("2. View Exam Word")
        print("3. View Answer Key")
        print("4. Save Exam")
        print("5. Submit to Principal")
        print("6. Create Another Exam")
        print("0. Main Menu")
        print()
        choice = _ask()
        if choice == "1":
            _open_path(wf.exam_pdf_path(rec.exam_id))
        elif choice == "2":
            _open_path(wf.exam_docx_path(rec.exam_id))
        elif choice == "3":
            _open_path(wf.answer_key_pdf_path(rec.exam_id))
        elif choice == "4":
            wf.save_exam(rec.exam_id)
            print("Exam saved.")
        elif choice == "5":
            try:
                rec = wf.submit_exam(rec.exam_id)
                print()
                print("Exam submitted to Principal.")
            except Exception as e:
                print(f"{e}")
        elif choice == "6":
            wf.reset_create_selection()
            return "create"
        elif choice == "0":
            return "main"
        else:
            print("Unknown option.")


def create_exam_menu(wf: TeacherWorkflow) -> None:
    while True:
        cfg = wf.get_current_config()
        _banner("CREATE EXAM")
        print()
        print(f"Teacher: {cfg.teacher_name}")
        print(f"Subject: {cfg.subject}")
        print(f"Grade: {cfg.grade}")
        print(f"Class: {cfg.class_id}")
        print()
        print("1. Select Chapters")
        print("2. Select Topics")
        print("3. Review Selection")
        print("4. Generate Exam")
        print("0. Back")
        print()
        choice = _ask()
        if choice == "1":
            select_chapters_ui(wf)
        elif choice == "2":
            select_topics_ui(wf)
        elif choice == "3":
            while True:
                review_choice = review_selection_ui(wf)
                if review_choice == "1":
                    if generate_exam_ui(wf):
                        nxt = exam_created_menu(wf)
                        if nxt == "create":
                            break
                        return
                elif review_choice == "2":
                    select_chapters_ui(wf)
                elif review_choice == "3":
                    select_topics_ui(wf)
                elif review_choice in ("0", None):
                    break
                else:
                    print("Unknown option.")
        elif choice == "4":
            if generate_exam_ui(wf):
                nxt = exam_created_menu(wf)
                if nxt == "create":
                    continue
                return
        elif choice == "0":
            return
        else:
            print("Unknown option.")


def exam_details_menu(wf: TeacherWorkflow, exam_id: str) -> None:
    while True:
        rec = wf.get_exam(exam_id)
        _banner("EXAM DETAILS")
        print()
        print(f"Exam ID: {rec.exam_id}")
        print(f"Subject: {rec.subject}")
        print(f"Grade: {rec.grade}")
        print(f"Class: {rec.class_id}")
        print(f"Created: {rec.created_at}")
        print(f"Status: {_status_label(rec.status)}")
        print("Chapters:")
        for name in rec.selected_chapters or []:
            print(f"- {name}")
        print()
        print("1. View Exam PDF")
        print("2. View Exam Word")
        print("3. View Answer Key")
        if rec.status == STATUS_DRAFT:
            print("4. Submit to Principal")
        print("0. Back")
        print()
        choice = _ask()
        if choice == "1":
            _open_path(wf.exam_pdf_path(rec.exam_id))
        elif choice == "2":
            _open_path(wf.exam_docx_path(rec.exam_id))
        elif choice == "3":
            _open_path(wf.answer_key_pdf_path(rec.exam_id))
        elif choice == "4" and rec.status == STATUS_DRAFT:
            try:
                wf.submit_exam(rec.exam_id)
                print()
                print("Exam submitted to Principal.")
            except Exception as e:
                print(f"{e}")
        elif choice == "0":
            return
        else:
            print("Unknown option.")


def my_exams_menu(wf: TeacherWorkflow) -> None:
    while True:
        exams = wf.list_my_exams()
        _banner("MY EXAMS")
        print()
        if not exams:
            print("No saved exams yet.")
            print()
            print("0. Back")
            print()
            if _ask() == "0":
                return
            continue
        for i, rec in enumerate(exams, start=1):
            print(
                f"{i}. {_format_date(rec.created_at)} | {rec.subject:<12} | "
                f"Grade {rec.grade} | {rec.status}"
            )
        print()
        print("0. Back")
        print()
        raw = _ask()
        if raw == "0":
            return
        try:
            n = int(raw)
            if 1 <= n <= len(exams):
                exam_details_menu(wf, exams[n - 1].exam_id)
            else:
                print("Unknown option.")
        except ValueError:
            print("Unknown option.")


def principal_feedback_menu(wf: TeacherWorkflow) -> None:
    items = wf.list_feedback()
    _banner("PRINCIPAL FEEDBACK")
    print()
    if not items:
        print("No Principal feedback yet.")
        print()
        print("0. Back")
        print()
        _ask()
        return
    for i, rec in enumerate(items, start=1):
        print(
            f"{i}. {_format_date(rec.created_at)} | {rec.subject:<12} | "
            f"{_status_label(rec.status)}"
        )
    print()
    print("0. Back")
    print()
    raw = _ask()
    if raw == "0":
        return
    try:
        n = int(raw)
        if n < 1 or n > len(items):
            print("Unknown option.")
            return
        rec = items[n - 1]
    except ValueError:
        print("Unknown option.")
        return
    while True:
        _banner("PRINCIPAL FEEDBACK")
        print()
        print(f"Subject: {rec.subject}")
        print(f"Exam ID: {rec.exam_id}")
        print(f"Status: {_status_label(rec.status)}")
        print()
        print("Feedback:")
        print(rec.principal_feedback or "(none)")
        print()
        print("1. View Exam PDF")
        print("2. View Exam Word")
        print("0. Back")
        print()
        choice = _ask()
        if choice == "1":
            _open_path(wf.exam_pdf_path(rec.exam_id))
        elif choice == "2":
            _open_path(wf.exam_docx_path(rec.exam_id))
        elif choice == "0":
            return
        else:
            print("Unknown option.")


def help_menu() -> None:
    while True:
        _banner("HELP")
        print()
        print("Basic Steps to Configure, Create, View & Share EXAM")
        print()
        print("1. Configure Exam")
        print("   - Select Subject")
        print("   - Select Grade")
        print("   - Save Config & Return")
        print()
        print("2. Create Exam")
        print("   - Select Chapters")
        print("   - Select Topics or use ALL")
        print("   - Review Selection")
        print("   - Generate Exam - can take up to 2 minutes")
        print()
        print("3. View and Share EXAM/Key")
        print("   - View EXAM PDF / Word file")
        print("   - Share / Print EXAM file")
        print("   - View Answer Key")
        print("   - Save EXAM")
        print("   - Submit to Principal")
        print()
        print("0. Back")
        print()
        if _ask() == "0":
            return


def main_menu(wf: TeacherWorkflow) -> None:
    while True:
        cfg = wf.get_current_config()
        _banner("TEACHER EXAM(Release 2)")
        print()
        print(f"Welcome, {cfg.teacher_name}")
        print()
        print("Default:")
        print(f"Grade {cfg.grade} | {cfg.subject} | Class {cfg.class_id}")
        print()
        print("1. Configure Exam")
        print("2. Create Exam")
        print("3. My Exams")
        print("4. Principal Feedback")
        print("5. Help")
        print("0. Exit")
        print()
        choice = _ask()
        try:
            if choice == "1":
                configure_exam(wf)
            elif choice == "2":
                create_exam_menu(wf)
            elif choice == "3":
                my_exams_menu(wf)
            elif choice == "4":
                principal_feedback_menu(wf)
            elif choice == "5":
                help_menu()
            elif choice == "0":
                print("Exit.")
                return
            else:
                print("Unknown option.")
        except Exception as e:
            print(f"{e}")


def run_teacher_terminal() -> None:
    wf = TeacherWorkflow()
    main_menu(wf)


def main() -> None:
    run_teacher_terminal()


if __name__ == "__main__":
    main()
