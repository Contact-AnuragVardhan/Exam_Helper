from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app import config
from services.logger import get_logger


log = get_logger("whatsapp.client")
MAX_TEXT = 3500


def mask_wa_id(wa_id: str | None) -> str:
    digits = "".join(ch for ch in str(wa_id or "") if ch.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def split_message(text: str, limit: int = MAX_TEXT) -> list[str]:
    body = (text or "").strip("\n")
    if not body:
        return [""]
    if len(body) <= limit:
        return [body]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in body.split("\n"):
        extra = len(line) + (1 if current else 0)
        if current and size + extra > limit:
            chunks.append("\n".join(current))
            current = [line]
            size = len(line)
        else:
            current.append(line)
            size += extra
    if current:
        chunks.append("\n".join(current))
    return chunks


@dataclass
class OutboundText:
    to: str
    text: str


@dataclass
class OutboundDocument:
    to: str
    filename: str
    caption: str = ""
    path: str = ""
    size_bytes: int = 0


@dataclass
class WhatsAppClient:
    """Meta WhatsApp Cloud API client. Pass mock=True only in local tests."""

    sent_texts: list[OutboundText] = field(default_factory=list)
    sent_documents: list[OutboundDocument] = field(default_factory=list)
    mock: bool = False

    def _credentials(self) -> tuple[str, str, str]:
        token = config.WHATSAPP_TOKEN.strip()
        phone_id = config.WHATSAPP_PHONE_NUMBER_ID.strip()
        version = config.WHATSAPP_GRAPH_VERSION.strip() or "v25.0"
        if not token or not phone_id:
            raise RuntimeError("WhatsApp credentials are not configured.")
        return token, phone_id, version

    def _messages_url(self) -> str:
        _token, phone_id, version = self._credentials()
        return f"https://graph.facebook.com/{version}/{phone_id}/messages"

    def _media_url(self) -> str:
        _token, phone_id, version = self._credentials()
        return f"https://graph.facebook.com/{version}/{phone_id}/media"

    def _headers(self) -> dict[str, str]:
        token, _phone_id, _version = self._credentials()
        return {"Authorization": f"Bearer {token}"}

    def send_text(self, to: str, text: str) -> None:
        for chunk in split_message(text):
            self.sent_texts.append(OutboundText(to=to, text=chunk))
            if self.mock:
                log.info("MOCK send_text to=%s chars=%s", mask_wa_id(to), len(chunk))
                continue
            self._api_send_text(to, chunk)

    def send_document(self, to: str, path: str | Path, filename: str | None = None, caption: str = "") -> None:
        pdf = Path(path)
        if not pdf.exists():
            raise FileNotFoundError(f"Document not found: {pdf}")
        self.send_document_bytes(to, pdf.read_bytes(), filename=filename or pdf.name, caption=caption, path=str(pdf))

    def send_document_bytes(
        self,
        to: str,
        content: bytes,
        *,
        filename: str,
        caption: str = "",
        path: str = "",
    ) -> None:
        data = bytes(content or b"")
        if not data:
            raise ValueError("Document content is empty.")
        self.sent_documents.append(
            OutboundDocument(
                to=to,
                filename=filename,
                caption=caption,
                path=path,
                size_bytes=len(data),
            )
        )
        if self.mock:
            log.info(
                "MOCK send_document to=%s filename=%s bytes=%s",
                mask_wa_id(to),
                filename,
                len(data),
            )
            return
        media_id = self._upload_media_bytes(data, filename)
        self._api_send_document(to, media_id=media_id, filename=filename, caption=caption)

    def mark_read(self, message_id: str | None) -> None:
        if not message_id or self.mock:
            return
        try:
            self._api_mark_read(message_id)
        except Exception:
            log.exception("mark_read failed message_id=%s", message_id)

    def _api_send_text(self, to: str, text: str) -> None:
        import httpx

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text, "preview_url": False},
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self._messages_url(), headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                log.error("send_text failed status=%s", resp.status_code)
                resp.raise_for_status()
        log.info("Text sent to=%s chars=%s", mask_wa_id(to), len(text))

    def _upload_media_bytes(self, content: bytes, filename: str) -> str:
        import httpx

        files = {
            "file": (filename, content, "application/pdf"),
            "messaging_product": (None, "whatsapp"),
            "type": (None, "application/pdf"),
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(self._media_url(), headers=self._headers(), files=files)
        if resp.status_code >= 400:
            log.error("media upload failed status=%s", resp.status_code)
            resp.raise_for_status()
        media_id = (resp.json() or {}).get("id")
        if not media_id:
            raise RuntimeError("WhatsApp media upload did not return an id.")
        log.info("Media uploaded filename=%s bytes=%s", filename, len(content))
        return str(media_id)

    def _api_send_document(self, to: str, media_id: str, filename: str, caption: str = "") -> None:
        import httpx

        document = {"id": media_id, "filename": filename}
        if caption:
            document["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": document,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self._messages_url(), headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                log.error("send_document failed status=%s", resp.status_code)
                resp.raise_for_status()
        log.info("Document sent to=%s filename=%s", mask_wa_id(to), filename)

    def _api_mark_read(self, message_id: str) -> None:
        import httpx

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(self._messages_url(), headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                resp.raise_for_status()

    def last_text(self) -> str:
        return self.sent_texts[-1].text if self.sent_texts else ""

    def all_text(self) -> str:
        return "\n".join(item.text for item in self.sent_texts)

    def clear(self) -> None:
        self.sent_texts.clear()
        self.sent_documents.clear()
