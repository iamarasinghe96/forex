import logging
from pathlib import Path

from forex.config import load_config
from forex.logging_setup import configure_logging


def test_request_urls_and_telegram_tokens_never_reach_logs(tmp_path: Path, capsys) -> None:
    config = load_config(Path("config.yaml"))
    config.logging.directory = tmp_path
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging(config)
        fake = "bot123456789:AAFakeToken_for-tests"
        logging.getLogger("httpx").info("HTTP Request: POST https://api.telegram.org/%s/sendMessage", fake)
        logging.getLogger("forex.alerts").warning("Delivery to https://api.telegram.org/%s failed", fake)
        for handler in root.handlers:
            handler.flush()
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:], root.level = saved
    written = (tmp_path / "forex.jsonl").read_text(encoding="utf-8") + capsys.readouterr().err
    assert "AAFakeToken" not in written
    assert "HTTP Request" not in written
    assert "bot<redacted>" in written
