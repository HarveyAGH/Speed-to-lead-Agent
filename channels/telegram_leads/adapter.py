from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

from channels.telegram_leads.sender import (
    send_telegram_acknowledgment,
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
    from app import normalize_lead_payload
    from tools.lead_ingestion import ingest_lead

    lead_id = f"tg_{uuid4().hex[:8]}"
    email_name = username or chat_id
    lead = normalize_lead_payload(
        {
            "lead_id": lead_id,
            "name": full_name,
            "email": f"lead+{email_name}@telegram.invalid",
            "company": "",
            "role": "",
            "source": "telegram",
            "service_interest": _extract_service_interest(text),
            "message": text,
            "budget": "",
            "timeline": "",
            "website": "",
            "status": "new",
        }
    )
    lead["source_channel"] = "telegram"
    lead["channel_user_id"] = chat_id

    result = ingest_lead(lead)
    logger.info(
        "telegram_lead_ingested lead_id=%s chat_id=%s status=%s",
        lead_id,
        chat_id,
        result.get("status"),
    )

    try:
        send_telegram_acknowledgment(chat_id=chat_id, lead_name=full_name)
    except Exception as exc:
        logger.warning(
            "telegram_lead_ack_failed lead_id=%s chat_id=%s error=%s",
            lead_id,
            chat_id,
            exc,
        )

    return {"lead_id": lead_id, "status": result.get("status")}


def _extract_service_interest(text: str) -> str:
    clean = text.strip()
    if len(clean) <= 200:
        return clean
    return f"{clean[:200].rstrip()}..."
