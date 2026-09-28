"""Optional phone alerts that always name the operating mode."""

from __future__ import annotations

import httpx

from forex.errors import OperatorError


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str, timeout_seconds: int, mode: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout_seconds
        self.mode = mode.upper()

    def send(self, message: str) -> None:
        try:
            response = httpx.post(self.url, json={"chat_id": self.chat_id, "text": f"[{self.mode}] {message}"}, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OperatorError(
                f"Telegram alert delivery failed: {exc}. Check the bot token, chat ID, and VPS "
                "internet connection. Trading must not rely on this alert having arrived."
            ) from exc
