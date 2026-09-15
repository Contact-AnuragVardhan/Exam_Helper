from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEST_DIR = Path(tempfile.mkdtemp(prefix="exam_helper_db_"))
DB_PATH = TEST_DIR / "exam_helper.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["DATABASE_AUTO_CREATE_TABLES"] = "true"
os.environ["VERIFY_TOKEN"] = "exam-helper-test-token"
os.environ["WHATSAPP_TOKEN"] = "test-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "123"

from fastapi.testclient import TestClient

from app.main import app
from database.models import (
    ExamHelperExamRow,
    ExamHelperProcessedMessageRow,
    ExamHelperSessionRow,
    TeacherProfileRow,
)
from database.session import db_session, init_db
from teacher_workflow.models import ExamRecord
from teacher_workflow.service import TeacherWorkflow
from teacher_workflow.storage import (
    get_answer_key_pdf_bytes,
    get_exam_pdf_bytes,
    get_exam_record,
    upsert_exam_record,
)
from whatsapp.adapter import WhatsAppAdapter
from whatsapp.client import WhatsAppClient
from whatsapp.session_store import SessionStore
from whatsapp.teachers import resolve_teacher_profile


def check(name: str, condition: bool) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        raise SystemExit(1)


init_db()
with db_session() as db:
    db.add_all(
        [
            TeacherProfileRow(
                id=101,
                whatsapp_number="+15551230001",
                teacher_name="Math Teacher",
                default_grade="10",
                default_subject="Maths",
                school_name="School A",
                preferred_language="Hinglish",
            ),
            TeacherProfileRow(
                id=102,
                whatsapp_number="15551230002",
                teacher_name="English Teacher",
                default_grade="Grade 10",
                default_subject="English",
                school_name="School B",
                preferred_language="English",
            ),
        ]
    )

math_profile = resolve_teacher_profile("+1 (555) 123-0001")
english_profile = resolve_teacher_profile("15551230002")
check("DB teacher lookup by formatted phone", math_profile is not None and math_profile.teacher_id == "101")
check("DB teacher name/subject", math_profile.teacher_name == "Math Teacher" and math_profile.subject == "Mathematics")
check("second number resolves separate teacher", english_profile is not None and english_profile.teacher_id == "102")

client = WhatsAppClient(mock=True)
adapter = WhatsAppAdapter(client=client, store=SessionStore())
reply = "\n".join(adapter.handle_text("15551230001", "Hi", "wamid.menu"))
check("WhatsApp menu uses DB teacher", "Welcome, Math Teacher" in reply)
check("processed webhook ID stored in DB", SessionStore().already_processed("wamid.menu"))

session = SessionStore().get("15551230001")
check("session persisted in DB", session is not None and session.teacher_id == "101")

record = ExamRecord(
    exam_id="db-exam-001",
    teacher_id="101",
    teacher_name="Math Teacher",
    grade=10,
    subject="Mathematics",
    class_id="10-A",
    selected_chapters=["Real Numbers"],
    selected_topics=["Euclid"],
    exam_pdf_path="db://exam_helper_exams/db-exam-001/exam.pdf",
    answer_key_pdf_path="db://exam_helper_exams/db-exam-001/answer_key.pdf",
    created_at=datetime.now().isoformat(timespec="seconds"),
    output_language="Hindi",
)
upsert_exam_record(
    record,
    artifacts={
        "exam_config": {"subject": "Mathematics"},
        "exam_json": {"questions": [{"id": "Q1"}]},
        "blueprint_json": {"marks": 80},
        "validation_json": {"ok": True},
        "llm_usage_json": {"total_tokens": 10},
        "allowed_content_json": {"chapters": ["Real Numbers"]},
        "exam_text": "EXAM",
        "answer_key_text": "ANSWER KEY",
        "validation_text": "PASS",
        "exam_pdf": b"%PDF-1.4\nexam\n",
        "answer_key_pdf": b"%PDF-1.4\nkey\n",
    },
)
check("exam metadata persisted in DB", get_exam_record("db-exam-001") is not None)
check("exam PDF persisted in DB", get_exam_pdf_bytes("db-exam-001").startswith(b"%PDF"))
check("answer-key PDF persisted in DB", get_answer_key_pdf_bytes("db-exam-001").startswith(b"%PDF"))

http = TestClient(app)
health = http.get("/health")
verify = http.get(
    "/webhook",
    params={"hub.mode": "subscribe", "hub.verify_token": "exam-helper-test-token", "hub.challenge": "12345"},
)
post = http.post("/webhook", json={"object": "whatsapp_business_account", "entry": []})
paths = {route.path for route in app.routes}
check("GET /health", health.status_code == 200 and health.json().get("status") == "ok")
check("GET /webhook Meta verification", verify.status_code == 200 and verify.text == "12345")
check("POST /webhook", post.status_code == 200)
check("no old /whatsapp/webhook route", "/whatsapp/webhook" not in paths)
check("no HTTP mock route", "/whatsapp/mock" not in paths)

with db_session() as db:
    check("session table populated", db.query(ExamHelperSessionRow).count() == 1)
    check("processed-message table populated", db.query(ExamHelperProcessedMessageRow).count() == 1)
    check("exam table populated", db.query(ExamHelperExamRow).count() == 1)

print("\nExam_Helper Render/DB/WhatsApp sanity PASS")
