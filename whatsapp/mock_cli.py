from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


from whatsapp.adapter import WhatsAppAdapter
from whatsapp.client import WhatsAppClient
from whatsapp.session_store import SessionStore


def main() -> None:
    wa_id = "15550001001"
    if len(sys.argv) > 1:
        wa_id = sys.argv[1]
    store = SessionStore()
    adapter = WhatsAppAdapter(client=WhatsAppClient(mock=True), store=store)
    print("Exam_Helper local mock CLI. Type messages. Ctrl+C to stop.")
    print(f"Teacher wa_id: {wa_id}")
    while True:
        try:
            text = input("Teacher> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text.lower() in {"quit", "exit"}:
            return
        adapter.handle_text(wa_id, text)


if __name__ == "__main__":
    main()
