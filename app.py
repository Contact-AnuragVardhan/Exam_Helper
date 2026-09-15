from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.logger import get_logger
from terminal.teacher_terminal import run_teacher_terminal


def main() -> None:
    log = get_logger("app")
    log.info("EXAM REV 2 teacher terminal startup")
    run_teacher_terminal()


def create_web_app():
    from fastapi import FastAPI

    from whatsapp.webhook import build_router

    web = FastAPI(title="EXAM REV 2")
    web.include_router(build_router())

    @web.get("/health")
    def health():
        return {"status": "ok"}

    return web


try:
    app = create_web_app()
except ImportError:
    app = None


if __name__ == "__main__":
    main()
