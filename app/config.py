from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value is not None and value != "" else default


APP_ENV = _get_env("APP_ENV", "dev")

# Logging. Console output is enabled by default for local development and Render.
LOG_LEVEL = _get_env("LOG_LEVEL", "INFO")
LOG_TO_CONSOLE = _get_env("LOG_TO_CONSOLE", "true").lower() == "true"
LOG_TO_FILE = _get_env("LOG_TO_FILE", "true").lower() == "true"
LOG_FILE = _get_env("LOG_FILE", str(ROOT / "logs" / "exam_helper.log"))

# Meta / WhatsApp. These names intentionally match Student Evaluator.
VERIFY_TOKEN = _get_env("VERIFY_TOKEN", "change_me")
WHATSAPP_TOKEN = _get_env("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = _get_env("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_GRAPH_VERSION = _get_env("WHATSAPP_GRAPH_VERSION", "v25.0")

# PostgreSQL. Render should always provide DATABASE_URL.
DATABASE_URL = _get_env("DATABASE_URL", "sqlite:///./exam_helper_local.db")
DATABASE_AUTO_CREATE_TABLES = _get_env("DATABASE_AUTO_CREATE_TABLES", "true").lower() == "true"

# Existing exam-generation settings remain unchanged.
OPENAI_API_KEY = _get_env("OPENAI_API_KEY", "")
OPENAI_MODEL = _get_env("OPENAI_MODEL", "gpt-4o")
MOCK_GENERATION = _get_env("MOCK_GENERATION", "false")
FAST_EXAM_MODE = _get_env("FAST_EXAM_MODE", "true")
HINDI_FONT_PATH = _get_env("HINDI_FONT_PATH", "")

# Local React simulator. Keep false on Render/production.
ENABLE_SIMULATOR = _get_env("ENABLE_SIMULATOR", "false").lower() == "true"
