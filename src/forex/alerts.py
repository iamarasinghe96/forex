"""Optional phone alerts that always name the operating mode."""

from __future__ import annotations

import httpx

from forex.errors import OperatorError


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str, timeout_seconds: int, mode: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.url = self.base + "sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout_seconds
        self.mode = mode.upper()

    def send(self, message: str) -> None:
        try:
            response = httpx.post(self.url, json={"chat_id": self.chat_id, "text": f"[{self.mode}] {message}"}, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError:
            raise OperatorError(
                "Telegram alert delivery failed. Check the bot token, chat ID, and VPS "
                "internet connection. Trading must not rely on this alert having arrived."
            ) from None

    def send_document(self, name: str, content: str, caption: str) -> None:
        """A text file the operator can open, copy or share (e.g. a review prompt for ChatGPT)."""
        try:
            response = httpx.post(self.base + "sendDocument",
                                  data={"chat_id": self.chat_id, "caption": f"[{self.mode}] {caption}"[:1024]},
                                  files={"document": (name, content.encode("utf-8"), "text/plain")},
                                  timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError:
            raise OperatorError(
                "Telegram file delivery failed. Check the bot token, chat ID, and VPS internet connection."
            ) from None
