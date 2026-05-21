from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("channel_dispatcher")


def dispatch_lead_response(
    *,
    source_channel: str,
    channel_user_id: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    if not source_channel or not channel_user_id:
        return {"ok": False, "reason": "missing source_channel or channel_user_id"}

    if source_channel == "whatsapp":
        return _dispatch_whatsapp(channel_user_id, subject, body)

    if source_channel == "telegram":
        return _dispatch_telegram(channel_user_id, subject, body)

    logger.info(
        "channel_dispatch_skipped source_channel=%s reason=unsupported_channel",
        source_channel,
    )
    return {
        "ok": True,
        "reason": f"no dispatch configured for channel: {source_channel}",
    }


def _dispatch_whatsapp(to: str, subject: str, body: str) -> dict[str, Any]:
    try:
        from channels.whatsapp.sender import send_whatsapp_message_sync

        result = send_whatsapp_message_sync(
            to=to,
            text=_format_channel_message(subject, body),
        )
        logger.info("channel_dispatch_whatsapp to=%s ok=%s", to, result.get("ok"))
        return {"ok": result.get("ok") is not False, "channel": "whatsapp", "result": result}
    except Exception as exc:
        logger.error("channel_dispatch_whatsapp_failed to=%s error=%s", to, exc)
        return {"ok": False, "channel": "whatsapp", "error": str(exc)}


def _dispatch_telegram(chat_id: str, subject: str, body: str) -> dict[str, Any]:
    try:
        from channels.telegram_leads.sender import send_telegram_lead_message

        result = send_telegram_lead_message(
            chat_id=chat_id,
            text=_format_channel_message(subject, body),
        )
        logger.info(
            "channel_dispatch_telegram chat_id=%s ok=%s",
            chat_id,
            result.get("ok"),
        )
        return {"ok": result.get("ok") is not False, "channel": "telegram", "result": result}
    except Exception as exc:
        logger.error("channel_dispatch_telegram_failed chat_id=%s error=%s", chat_id, exc)
        return {"ok": False, "channel": "telegram", "error": str(exc)}


def _format_channel_message(subject: str, body: str) -> str:
    parts = []
    if subject and subject.strip():
        parts.extend([f"Subject: {_normalize_message_text(subject).strip()}", ""])
    if body and body.strip():
        parts.append(_normalize_message_text(body).strip())
    return "\n".join(parts)


def _normalize_message_text(text: str) -> str:
    return (
        str(text or "")
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
    )
