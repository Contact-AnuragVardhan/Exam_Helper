from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete

from database.models import ExamHelperProcessedMessageRow, ExamHelperSessionRow
from database.session import db_session
from services.logger import get_logger
from whatsapp.adapter import WhatsAppAdapter
from whatsapp.client import WhatsAppClient, mask_wa_id
from whatsapp.session_store import SessionStore
from whatsapp.teachers import normalize_wa_id, resolve_teacher_profile


log = get_logger("simulator")


class SimulatorSendRequest(BaseModel):
    phone_number: str
    text: str


class SimulatorResetRequest(BaseModel):
    phone_number: str


@dataclass
class SimulatorMessage:
    id: int
    phone_number: str
    type: str
    body: str = ""
    filename: str = ""
    caption: str = ""
    document_id: str = ""
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "phone_number": self.phone_number,
            "type": self.type,
            "body": self.body,
            "filename": self.filename,
            "caption": self.caption,
            "document_id": self.document_id,
            "size_bytes": self.size_bytes,
        }


@dataclass
class LocalSimulatorStore:
    histories: dict[str, list[SimulatorMessage]] = field(default_factory=dict)
    documents: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    _next_id: int = 1
    _lock: RLock = field(default_factory=RLock)

    def _phone(self, value: str) -> str:
        return normalize_wa_id(value)

    def add_message(self, phone_number: str, msg_type: str, **kwargs) -> SimulatorMessage:
        phone = self._phone(phone_number)
        with self._lock:
            message = SimulatorMessage(
                id=self._next_id,
                phone_number=phone,
                type=msg_type,
                **kwargs,
            )
            self._next_id += 1
            self.histories.setdefault(phone, []).append(message)
            return message

    def history(self, phone_number: str) -> list[dict]:
        phone = self._phone(phone_number)
        with self._lock:
            return [message.to_dict() for message in self.histories.get(phone, [])]

    def add_document(self, phone_number: str, content: bytes, filename: str, caption: str = "") -> SimulatorMessage:
        document_id = uuid4().hex
        with self._lock:
            self.documents[document_id] = (bytes(content), filename)
        return self.add_message(
            phone_number,
            "document",
            filename=filename,
            caption=caption,
            document_id=document_id,
            size_bytes=len(content),
        )

    def get_document(self, document_id: str) -> tuple[bytes, str] | None:
        with self._lock:
            return self.documents.get(document_id)

    def reset(self, phone_number: str) -> None:
        phone = self._phone(phone_number)
        with self._lock:
            old = self.histories.pop(phone, [])
            for message in old:
                if message.document_id:
                    self.documents.pop(message.document_id, None)


_store = LocalSimulatorStore()


class SimulatorWhatsAppClient(WhatsAppClient):
    def __init__(self, store: LocalSimulatorStore):
        super().__init__(mock=True)
        self.simulator_store = store

    def send_text(self, to: str, text: str) -> None:
        super().send_text(to, text)
        # Match the exact chunking used by the real WhatsApp client.
        from whatsapp.client import split_message
        for chunk in split_message(text):
            self.simulator_store.add_message(to, "text", body=chunk)

    def send_document_bytes(
        self,
        to: str,
        content: bytes,
        *,
        filename: str,
        caption: str = "",
        path: str = "",
    ) -> None:
        super().send_document_bytes(
            to,
            content,
            filename=filename,
            caption=caption,
            path=path,
        )
        self.simulator_store.add_document(to, content, filename, caption)


def _teacher_summary(phone_number: str) -> dict | None:
    try:
        profile = resolve_teacher_profile(phone_number)
    except Exception:
        return None
    if profile is None:
        return None
    return {
        "teacher_id": profile.teacher_id,
        "teacher_name": profile.teacher_name,
        "grade": profile.grade,
        "subject": profile.subject,
        "school_name": profile.school_name,
        "preferred_language": profile.preferred_language,
    }


def _state(phone_number: str) -> str:
    session = SessionStore().get(phone_number)
    return session.state if session is not None else "START"


def _response(phone_number: str, new_messages: list[dict] | None = None) -> dict:
    phone = normalize_wa_id(phone_number)
    return {
        "phone_number": phone,
        "state": _state(phone),
        "teacher": _teacher_summary(phone),
        "history": _store.history(phone),
        "new_messages": new_messages or [],
    }


def build_simulator_router() -> APIRouter:
    router = APIRouter(prefix="/simulator", tags=["Local Simulator"])

    @router.get("/history")
    def history(phone_number: str = Query(...)):
        log.info("Simulator history requested wa_id=%s", mask_wa_id(phone_number))
        return _response(phone_number)

    @router.post("/send")
    def send(request: SimulatorSendRequest):
        phone = normalize_wa_id(request.phone_number)
        text = request.text.strip()
        if not phone:
            raise HTTPException(status_code=400, detail="Phone number is required.")
        if not text:
            raise HTTPException(status_code=400, detail="Text is required.")

        log.info("Simulator message received wa_id=%s chars=%s", mask_wa_id(phone), len(text))
        before = len(_store.history(phone))
        _store.add_message(phone, "incoming", body=text)

        client = SimulatorWhatsAppClient(_store)
        adapter = WhatsAppAdapter(client=client)
        adapter.handle_text(phone, text, message_id=f"sim-{uuid4().hex}")

        history_now = _store.history(phone)
        log.info(
            "Simulator message processed wa_id=%s responses=%s",
            mask_wa_id(phone),
            len(history_now) - before - 1,
        )
        return _response(phone, new_messages=history_now[before:])

    @router.post("/reset")
    def reset(request: SimulatorResetRequest):
        phone = normalize_wa_id(request.phone_number)
        if not phone:
            raise HTTPException(status_code=400, detail="Phone number is required.")

        log.info("Simulator reset requested wa_id=%s", mask_wa_id(phone))
        _store.reset(phone)
        with db_session() as db:
            db.execute(delete(ExamHelperSessionRow).where(ExamHelperSessionRow.wa_id == phone))
            db.execute(delete(ExamHelperProcessedMessageRow).where(ExamHelperProcessedMessageRow.wa_id == phone))
        return _response(phone)

    from pathlib import Path

    @router.get("/document/{document_id}")
    def document(document_id: str):
        item = _store.get_document(document_id)

        if item is None:
            log.warning(
                "Simulator document not found document_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Document not found or simulator was restarted.",
            )

        content, filename = item

        safe_name = filename.replace('"', "") or "document"
        suffix = Path(safe_name).suffix.lower()

        if suffix == ".docx":
            media_type = (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            )
        else:
            media_type = "application/pdf"

        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition":
                    f'inline; filename="{safe_name}"'
            },
        )

    return router
