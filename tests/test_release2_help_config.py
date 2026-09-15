from whatsapp.adapter import HELP_TEXT, WhatsAppAdapter
from whatsapp.client import WhatsAppClient


class _ReviewWorkflow:
    def review_configuration(self):
        return {
            "teacher_name": "Test Teacher",
            "grade": 10,
            "subject": "Mathematics",
            "class_id": "10-A",
            "output_language": "Hindi",
            "selected_chapters": ["Real Numbers", "Polynomials"],
            "selected_topics": ["Fundamental Theorem of Arithmetic", "Introduction"],
            "question_source": "BOOK",
            "exam_profile": "Grade 10 Mathematics",
            "topics_are_all": False,
        }


def test_release2_help_matches_grouped_client_steps():
    assert "Basic Steps to Configure, Create, View & Share EXAM" in HELP_TEXT
    assert "1. Configure Exam" in HELP_TEXT
    assert "2. Create Exam" in HELP_TEXT
    assert "3. View and Share EXAM/Key" in HELP_TEXT
    assert "Generate Exam - can take up to 2 minutes" in HELP_TEXT
    assert "View EXAM PDF / Word file" in HELP_TEXT
    assert "View Answer Key" in HELP_TEXT
    assert "Save EXAM" in HELP_TEXT


def test_review_exam_config_displays_chapters_not_topic_names():
    client = WhatsAppClient(mock=True)
    adapter = WhatsAppAdapter(client=client)
    adapter._send_review("15555550123", _ReviewWorkflow())

    text = client.last_text()
    assert "Chapters:" in text
    assert "- Real Numbers" in text
    assert "- Polynomials" in text
    assert "\nTopics:" not in text
    assert "Fundamental Theorem of Arithmetic" not in text
    assert "\n3. Change Topics" in text
