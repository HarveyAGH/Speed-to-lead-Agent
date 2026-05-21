from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger("whatsapp.adapter")


def register_whatsapp(app: FastAPI) -> None:
    @app.get("/whatsapp/webhook")
    def whatsapp_verify(request: Request):
        params = dict(request.query_params)
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

        if mode == "subscribe" and token and token == verify_token:
            logger.info("whatsapp_webhook_verified")
            return PlainTextResponse(content=challenge or "")

        raise HTTPException(status_code=403, detail="Webhook verification failed")

    @app.post("/whatsapp/webhook")
    async def whatsapp_inbound(request: Request) -> dict[str, Any]:
        body_bytes = await request.body()
        app_secret = os.getenv("WHATSAPP_APP_SECRET", "")
        if app_secret:
            signature = request.headers.get("X-Hub-Signature-256", "")
            if not _verify_meta_signature(body_bytes, app_secret, signature):
                logger.warning("whatsapp_webhook_invalid_signature")
                raise HTTPException(status_code=401, detail="Invalid Meta signature")

        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

        return {"ok": True, "result": handle_whatsapp_payload(payload)}


def handle_whatsapp_payload(payload: dict[str, Any]) -> dict[str, Any]:
    results = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {item.get("wa_id"): item for item in value.get("contacts", [])}
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    logger.info(
                        "whatsapp_message_ignored type=%s",
                        message.get("type"),
                    )
                    continue

                wa_number = str(message.get("from") or "")
                text = str((message.get("text") or {}).get("body") or "").strip()
                if not wa_number or not text:
                    continue

                profile = (contacts.get(wa_number) or {}).get("profile") or {}
                results.append(
                    _ingest_whatsapp_lead(
                        wa_number=wa_number,
                        text=text,
                        contact_name=str(profile.get("name") or ""),
                    )
                )

    return {"processed": len(results), "leads": results}


def _ingest_whatsapp_lead(
    *,
    wa_number: str,
    text: str,
    contact_name: str = "",
) -> dict[str, Any]:
    from tools.channel_intake import ingest_channel_message

    result = ingest_channel_message(
        source_channel="whatsapp",
        channel_user_id=wa_number,
        text=text,
        sender_name=contact_name or wa_number,
    )

    logger.info(
        "whatsapp_channel_message_queued lead_id=%s status=%s",
        result.get("lead_id"),
        result.get("status"),
    )

    return result


def _verify_meta_signature(body: bytes, app_secret: str, header: str) -> bool:
    if not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, header)

