from __future__ import annotations

import logging
import os
from typing import Any

from channels.telegram_leads.sender import (
    send_telegram_lead_message,
)

logger = logging.getLogger("telegram_leads.adapter")


def handle_telegram_lead_message(message: dict[str, Any]) -> dict[str, Any]:
    from_user = message.get("from") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or from_user.get("id") or "")
    text = str(message.get("text") or "").strip()
    first_name = str(from_user.get("first_name") or "")
    last_name = str(from_user.get("last_name") or "")
    username = str(from_user.get("username") or "")
    full_name = f"{first_name} {last_name}".strip() or username or chat_id

    if not chat_id:
        logger.warning("telegram_lead_ignored reason=missing_chat_id")
        return {"ok": False, "reason": "missing_chat_id"}

    if not text:
        send_telegram_lead_message(
            chat_id=chat_id,
            text=(
                "Please send a text message describing what you need, and I will "
                "make sure the right person gets back to you."
            ),
        )
        return {"ok": True, "reason": "non_text_message_prompted"}

    return _ingest_telegram_lead(
        chat_id=chat_id,
        text=text,
        full_name=full_name,
        username=username,
    )


def is_owner_chat(chat_id: str) -> bool:
    owner_id = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")
    return bool(owner_id and str(chat_id) == str(owner_id))


def _ingest_telegram_lead(
    *,
    chat_id: str,
    text: str,
    full_name: str,
    username: str,
) -> dict[str, Any]:
    from tools.channel_intake import ingest_channel_message

    result = ingest_channel_message(
        source_channel="telegram",
        channel_user_id=chat_id,
        text=text,
        sender_name=full_name,
        username=username,
    )

    logger.info(
        "telegram_channel_message_queued lead_id=%s chat_id=%s status=%s",
        result.get("lead_id"),
        chat_id,
        result.get("status"),
    )

    return result
