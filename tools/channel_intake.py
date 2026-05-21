from __future__ import annotations

from typing import Any
from uuid import uuid4

from tools.channel_conversations import (
    append_channel_message,
    get_or_create_conversation,
)
from tools.job_queue import enqueue_lead_job, queue_is_configured


def ingest_channel_message(
    *,
    source_channel: str,
    channel_user_id: str,
    text: str,
    sender_name: str = "",
    username: str = "",
) -> dict[str, Any]:
    if not queue_is_configured():
        return {
            "status": "error",
            "error": "POSTGRES_DB_URI is required for channel message processing",
            "http_status": 500,
        }

    lead_id = f"{_channel_prefix(source_channel)}_{uuid4().hex[:8]}"
    conversation = get_or_create_conversation(
        source_channel=source_channel,
        channel_user_id=channel_user_id,
        lead_id=lead_id,
    )
    lead_id = str(conversation["lead_id"])

    message = append_channel_message(
        conversation_id=int(conversation["id"]),
        role="customer",
        content=text,
    )

    payload = {
        "job_type": "channel_message",
        "lead_id": lead_id,
        "conversation_id": conversation["id"],
        "message_id": message["id"],
        "source_channel": source_channel,
        "channel_user_id": channel_user_id,
        "sender_name": sender_name,
        "username": username,
        "text": text,
    }
    job = enqueue_lead_job(
        lead_id,
        payload,
        job_type="channel_message",
    )

    return {
        "status": "queued",
        "lead_id": lead_id,
        "conversation_id": conversation["id"],
        "message_id": message["id"],
        "job": job,
    }


def _channel_prefix(source_channel: str) -> str:
    if source_channel == "telegram":
        return "tg"
    if source_channel == "whatsapp":
        return "wa"
    return "ch"
