"""Human console and durable JSON-lines logging with mode on every record."""

from __future__ import annotations

import json
import logging
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


def configure_logging(config: AppConfig) -> None:
    config.logging.directory.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    mode_filter = ModeFilter(config.mode)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s [%(mode)s] %(levelname)s %(message)s"))
    console.addFilter(mode_filter)
    durable = RotatingFileHandler(
        config.logging.directory / "forex.jsonl", maxBytes=config.logging.max_bytes,
        backupCount=config.logging.backup_count, encoding="utf-8",
    )
    durable.setFormatter(JsonFormatter())
    durable.addFilter(mode_filter)
    root.addHandler(console)
    root.addHandler(durable)
