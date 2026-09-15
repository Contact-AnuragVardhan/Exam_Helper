from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

LOGGER_NAME = "exam_helper"
DEFAULT_LOG_FILE = ROOT / "logs" / "exam_helper.log"
SECRET_KEYS = (
    "OPENAI_API_KEY",
    "API_KEY",
    "SECRET",
    "WHATSAPP_TOKEN",
    "VERIFY_TOKEN",
    "DATABASE_URL",
)
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]+)")
URL_CREDENTIALS_RE = re.compile(r"(://[^:/\s]+:)[^@/\s]+(@)")
_configured = False


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _log_level() -> int:
    value = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, value, logging.INFO)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = str(record.getMessage())
        message = SECRET_RE.sub("sk-***REDACTED***", message)
        message = URL_CREDENTIALS_RE.sub(r"\1***REDACTED***\2", message)
        for key in SECRET_KEYS:
            value = os.environ.get(key, "")
            if value:
                message = message.replace(value, "***REDACTED***")
        record.msg = message
        record.args = ()
        return True


def configure_logging(force: bool = False) -> logging.Logger:
    global _configured

    logger = logging.getLogger(LOGGER_NAME)
    if _configured and not force:
        return logger

    if force:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    logger.setLevel(_log_level())
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if _env_bool("LOG_TO_CONSOLE", True):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.addFilter(RedactFilter())
        logger.addHandler(console)

    if _env_bool("LOG_TO_FILE", True):
        log_path = Path(os.getenv("LOG_FILE", str(DEFAULT_LOG_FILE))).expanduser()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=int(os.getenv("LOG_MAX_BYTES", "5000000")),
                backupCount=int(os.getenv("LOG_BACKUP_COUNT", "5")),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(RedactFilter())
            logger.addHandler(file_handler)
        except (OSError, ValueError):
            logger.exception("Could not configure file logging path=%s", log_path)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    _configured = True
    return logger


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    configure_logging()
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
