# Exam_Helper

Exam_Helper is a WhatsApp-oriented backend for teachers to create Grade 10 Mathematics and English exam papers from the project's imported textbook content and exam-generation engines.

## WhatsApp flow

`WhatsApp sender number -> teacher_profile DB lookup -> teacher-specific session -> chapter/topic selection -> exam generation -> exam + answer-key PDFs -> PostgreSQL -> WhatsApp document send`

Teacher identity is no longer read from one global `config/teacher_profile.json`. The inbound WhatsApp number is normalized and looked up in the existing `teacher_profile` database table.

## Student Evaluator-compatible endpoint contract

- FastAPI target: `app.main:app`
- Health: `GET /health`
- Meta verification: `GET /webhook`
- Meta inbound messages: `POST /webhook`
- Verify token env: `VERIFY_TOKEN`
- WhatsApp access token env: `WHATSAPP_TOKEN`
- Phone Number ID env: `WHATSAPP_PHONE_NUMBER_ID`
- Graph version env: `WHATSAPP_GRAPH_VERSION`
- Database: PostgreSQL

## Database persistence

Application state is stored in PostgreSQL rather than JSON files or a Render persistent disk.

- `teacher_profile` — existing shared teacher profile table.
- `exam_helper_sessions` — WhatsApp state and selections.
- `exam_helper_processed_messages` — inbound message dedupe.
- `exam_helper_exams` — exam metadata, status, feedback, generation data, exam PDF and answer-key PDF.

`DATABASE_AUTO_CREATE_TABLES=true` creates the Exam_Helper tables at startup without replacing the existing `teacher_profile` table.

## Local development

Copy `.env.example` to `.env`, configure `DATABASE_URL`, then:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/docs` or check `http://127.0.0.1:8000/health`.

Application logs print in the same terminal and are also written to
`logs/exam_helper.log`. Set `LOG_LEVEL=DEBUG` for more detail, or use
`LOG_TO_FILE=false` to keep console-only logging.

For a local WhatsApp-style conversation without Meta deployment:

```bash
python -m whatsapp.mock_cli 919691437223
```

The number must already exist in `teacher_profile`.

For the terminal workflow, set `LOCAL_TEACHER_WHATSAPP_NUMBER` and run:

```bash
python terminal_main.py
```

See `RENDER_DEPLOYMENT.md` for Render and Meta setup.
