from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.request import Request

from tools.http_client import request_json_with_retries

logger = logging.getLogger("whatsapp.sender")

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
MAX_WHATSAPP_MESSAGE_CHARS = 4096


def send_whatsapp_message_sync(to: str, text: str) -> dict[str, Any]:
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")

    if not phone_id or not token:
        logger.warning(
            "whatsapp_send_skipped reason=missing_config to=%s",
            to,
        )
        return {"ok": False, "reason": "whatsapp_not_configured"}

    last_result: dict[str, Any] = {}
    for chunk in _chunks(text, MAX_WHATSAPP_MESSAGE_CHARS):
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": chunk},
        }
        request = Request(
            f"{GRAPH_API_BASE}/{phone_id}/messages",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            last_result = request_json_with_retries(request, timeout=20)
        except RuntimeError as exc:
            logger.error("whatsapp_send_failed to=%s error=%s", to, exc)
            return {"ok": False, "error": str(exc)}

    return {"ok": True, "meta_response": last_result}


def send_whatsapp_acknowledgment(to: str, lead_name: str = "") -> dict[str, Any]:
    greeting = f"Hi {lead_name}! " if lead_name else "Hi! "
    text = (
        f"{greeting}Thanks for reaching out. "
        "I received your message and will reply shortly with a personalized response."
    )
    return send_whatsapp_message_sync(to=to, text=text)


def _chunks(text: str, size: int) -> list[str]:
    clean = text or ""
    if not clean:
        return [""]
    return [clean[index : index + size] for index in range(0, len(clean), size)]
