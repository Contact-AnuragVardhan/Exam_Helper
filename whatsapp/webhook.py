from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app import config
from services.logger import get_logger

from .adapter import WhatsAppAdapter
from .client import WhatsAppClient, mask_wa_id
from .teachers import normalize_wa_id


log = get_logger("whatsapp.webhook")


@dataclass
class InboundMessage:
    wa_id: str
    message_id: str
    msg_type: str
    text: str


def extract_inbound(payload: dict) -> list[InboundMessage]:
    out: list[InboundMessage] = []
    if not isinstance(payload, dict):
        return out
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            messages = value.get("messages") or []
            if not messages:
                continue
            contacts = value.get("contacts") or []
            contact_wa = ""
            if contacts and isinstance(contacts[0], dict):
                contact_wa = normalize_wa_id(contacts[0].get("wa_id"))
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                wa_id = contact_wa or normalize_wa_id(msg.get("from"))
                mid = str(msg.get("id") or "")
                mtype = str(msg.get("type") or "")
                text = ""
                if mtype == "text":
                    text = str((msg.get("text") or {}).get("body") or "")
                out.append(InboundMessage(wa_id=wa_id, message_id=mid, msg_type=mtype, text=text))
    return out


_adapter: WhatsAppAdapter | None = None


def get_adapter() -> WhatsAppAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WhatsAppAdapter(client=WhatsAppClient())
    return _adapter


def process_inbound(message: InboundMessage, adapter: WhatsAppAdapter | None = None) -> None:
    adapter = adapter or get_adapter()
    log.info(
        "inbound wa_id=%s message_id=%s type=%s",
        mask_wa_id(message.wa_id),
        message.message_id,
        message.msg_type,
    )
    adapter.client.mark_read(message.message_id)
    if message.msg_type != "text":
        adapter.handle_unsupported(message.wa_id, message.message_id)
        return
    adapter.handle_text(message.wa_id, message.text, message.message_id)


def verify_token_ok(mode: str | None, token: str | None) -> bool:
    return mode == "subscribe" and bool(config.VERIFY_TOKEN) and token == config.VERIFY_TOKEN


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/webhook")
    def verify_webhook(
        hub_mode: str | None = Query(default=None, alias="hub.mode"),
        hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
        hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    ):
        if verify_token_ok(hub_mode, hub_verify_token):
            log.info("Webhook verification succeeded")
            return PlainTextResponse(content=str(hub_challenge or ""), status_code=200)
        log.warning("Webhook verification rejected mode=%s", hub_mode)
        return PlainTextResponse(content="Forbidden", status_code=403)

    @router.post("/webhook")
    async def inbound_webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            payload = await request.json()
        except Exception:
            log.exception("webhook json parse failed")
            # Meta retries non-2xx responses. Keep malformed/status payloads harmless.
            return JSONResponse({"status": "ok"}, status_code=200)

        messages = extract_inbound(payload)
        log.info("Webhook payload accepted messages=%s", len(messages))
        for message in messages:
            background_tasks.add_task(process_inbound, message)
        return JSONResponse({"status": "ok"}, status_code=200)

    return router
