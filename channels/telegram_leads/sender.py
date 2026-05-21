from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from tools.http_client import request_json_with_retries

logger = logging.getLogger("telegram_leads.sender")

MAX_TELEGRAM_MESSAGE_CHARS = 4096


def send_telegram_lead_message(chat_id: str, text: str) -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("telegram_lead_send_skipped reason=missing_token chat_id=%s", chat_id)
        return {"ok": False, "reason": "telegram_not_configured"}

    last_result: dict[str, Any] = {}
    for chunk in _chunks(text, MAX_TELEGRAM_MESSAGE_CHARS):
        request = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=urlencode(
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                }
            ).encode("utf-8"),
            method="POST",
        )
        try:
            last_result = request_json_with_retries(request, timeout=15)
        except RuntimeError as exc:
            logger.error("telegram_lead_send_failed chat_id=%s error=%s", chat_id, exc)
            return {"ok": False, "error": str(exc)}

    return last_result


def send_telegram_acknowledgment(chat_id: str, lead_name: str = "") -> dict[str, Any]:
    first_name = lead_name.split()[0] if lead_name else ""
    greeting = f"Hi {first_name}! " if first_name else "Hi! "
    return send_telegram_lead_message(
        chat_id=chat_id,
        text=(
            f"{greeting}Thanks for reaching out.\n\n"
            "I received your message and will respond shortly with a personalized reply."
        ),
    )


def _chunks(text: str, size: int) -> list[str]:
    clean = text or ""
    if not clean:
        return [""]
    return [clean[index : index + size] for index in range(0, len(clean), size)]
