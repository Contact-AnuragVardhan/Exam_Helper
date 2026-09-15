# Exam_Helper — Render + WhatsApp deployment

This version intentionally follows the same public WhatsApp contract as Student Evaluator.

## Public contract

| Setting | Exam_Helper |
|---|---|
| FastAPI target | `app.main:app` |
| Health | `/health` |
| Meta GET verification | `/webhook` |
| Meta POST inbound | `/webhook` |
| Local mock HTTP endpoint | none |
| Verify token env | `VERIFY_TOKEN` |
| WhatsApp token env | `WHATSAPP_TOKEN` |
| Phone Number ID env | `WHATSAPP_PHONE_NUMBER_ID` |
| Graph version env | `WHATSAPP_GRAPH_VERSION` |
| Database | PostgreSQL |
| Render start target | `app.main:app` |

Meta callback URL:

`https://<your-exam-helper-service>.onrender.com/webhook`

## PostgreSQL persistence

The app no longer persists WhatsApp or exam state in JSON files or a Render disk.

It uses the existing `teacher_profile` table for teacher lookup and creates these Exam_Helper tables automatically when `DATABASE_AUTO_CREATE_TABLES=true`:

- `exam_helper_sessions` — conversation state and current exam selections.
- `exam_helper_processed_messages` — webhook message-id deduplication.
- `exam_helper_exams` — exam metadata, status, feedback, generated JSON/text payloads, exam PDF, exam Word document, and answer-key PDF.

Generated files are only temporary build artifacts. The durable PDF/Word artifacts and generation payload are stored in PostgreSQL, so no Render persistent disk is required.

## Required Render variables

Set these as secrets/environment variables in Render:

```text
VERIFY_TOKEN
WHATSAPP_TOKEN
WHATSAPP_PHONE_NUMBER_ID
DATABASE_URL
OPENAI_API_KEY
```

Useful non-secret/default variables are already in `render.yaml`:

```text
WHATSAPP_GRAPH_VERSION=v25.0
DATABASE_AUTO_CREATE_TABLES=true
OPENAI_MODEL=gpt-4o
MOCK_GENERATION=false
FAST_EXAM_MODE=true
```

If Hindi PDF output is required on Linux, set `HINDI_FONT_PATH` to an installed Devanagari-capable font after the renderer/font package is configured for that host.

## Deploy

1. Push the project to the Git repository used by Render.
2. Create the service from `render.yaml` or configure the same values manually.
3. Set `DATABASE_URL` to the PostgreSQL database that already contains `teacher_profile`.
4. Set the Meta and OpenAI secrets.
5. Deploy.
6. Verify `GET https://<service>.onrender.com/health` returns `{"status":"ok"}`.
7. In Meta WhatsApp configuration set callback URL to `https://<service>.onrender.com/webhook` and use exactly the same value as Render `VERIFY_TOKEN`.
8. Subscribe the app to WhatsApp `messages` events.

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health:

`http://127.0.0.1:8000/health`

Webhook verification example:

```bash
curl "http://127.0.0.1:8000/webhook?hub.mode=subscribe&hub.verify_token=change_me&hub.challenge=12345"
```

There is deliberately no `/whatsapp/mock` HTTP route, matching Student Evaluator. For local conversation testing use:

```bash
python -m whatsapp.mock_cli <teacher_whatsapp_number>
```

The teacher number must exist in the `teacher_profile` table of the configured database.
