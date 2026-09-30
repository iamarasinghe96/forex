"""Human console and durable JSON-lines logging with mode on every record."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from forex.config import AppConfig


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": getattr(record, "mode", "UNKNOWN"),
            "level": record.levelname, "logger": record.name, "message": record.getMessage(),
        }, ensure_ascii=False)


class ModeFilter(logging.Filter):
    def __init__(self, mode: str):
        super().__init__()
        self.mode = mode.upper()

    def filter(self, record: logging.LogRecord) -> bool:
        record.mode = self.mode
        return True


class SecretRedactionFilter(logging.Filter):
    """Telegram puts the bot token in the request URL; never let it reach console or files."""

    TELEGRAM_TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.TELEGRAM_TOKEN.sub("bot<redacted>", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def configure_logging(config: AppConfig) -> None:
    config.logging.directory.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    # httpx logs every request URL at INFO, which includes the Telegram bot token.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    mode_filter = ModeFilter(config.mode)
    redaction = SecretRedactionFilter()
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s [%(mode)s] %(levelname)s %(message)s"))
    console.addFilter(mode_filter)
    console.addFilter(redaction)
    durable = RotatingFileHandler(
        config.logging.directory / "forex.jsonl", maxBytes=config.logging.max_bytes,
        backupCount=config.logging.backup_count, encoding="utf-8",
    )
    durable.setFormatter(JsonFormatter())
    durable.addFilter(mode_filter)
    durable.addFilter(redaction)
    root.addHandler(console)
    root.addHandler(durable)
