from pathlib import Path
from zipfile import ZipFile

from services.renderer import render_exam_docx


def _sample_exam():
    return {
        "exam_name": "Mathematics Examination",
        "subject": "Mathematics",
        "grade": 10,
        "total_marks": 3,
        "duration_minutes": 30,
        "header": {
            "school_line": "Teacher Exam",
            "exam_title": "Mathematics Examination",
            "grade": 10,
            "subject": "Mathematics",
            "total_marks": 3,
            "duration_minutes": 30,
            "instructions": ["सभी प्रश्न अनिवार्य हैं।"],
        },
        "syllabus": {"groups": [{"book": "NCERT Mathematics", "items": ["वास्तविक संख्याएँ"]}]},
        "questions": [
            {
                "question_number": 1,
                "section_heading": "प्रश्न",
                "question_text_hindi": "यूक्लिड विभाजन प्रमेय लिखिए।",
                "answer_key_hindi": "a=bq+r",
                "marks": 3,
                "content_class": "SHORT",
            }
        ],
    }


def test_exam_docx_is_created_with_exam_content(tmp_path: Path):
    target = tmp_path / "exam.docx"
    render_exam_docx(_sample_exam(), target)
    assert target.exists() and target.stat().st_size > 0
    with ZipFile(target) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "Mathematics Examination" in xml
    assert "यूक्लिड विभाजन प्रमेय" in xml
