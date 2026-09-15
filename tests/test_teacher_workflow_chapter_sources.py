from __future__ import annotations

from teacher_workflow.models import TeacherProfile
from teacher_workflow.service import TeacherWorkflow


def _profile(subject: str) -> TeacherProfile:
    return TeacherProfile(
        teacher_id=f"test-{subject.lower()}",
        teacher_name="Test Teacher",
        grade=10,
        subject=subject,
        class_id="10A",
        output_language="English",
    )


def test_math_chapters_are_unchanged():
    chapters = TeacherWorkflow(profile=_profile("Mathematics")).get_available_chapters()
    assert len(chapters) == 14
    assert [c.chapter_name for c in chapters[:5]] == [
        "Real Numbers",
        "Polynomials",
        "Pair of Linear Equations in Two Variables",
        "Quadratic Equations",
        "Arithmetic Progressions",
    ]


def test_english_q1_chapters_are_loaded_from_bundled_syllabus():
    chapters = TeacherWorkflow(profile=_profile("English")).get_available_chapters()
    assert [c.chapter_name for c in chapters] == [
        "A Letter to God",
        "Dust of Snow",
        "Fire and Ice",
        "Nelson Mandela: Long Walk to Freedom",
        "Two Stories about Flying",
    ]
