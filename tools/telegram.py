from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from config import PUBLIC_BASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID
from tools.http_client import request_json_with_retries
from tools.owner_config import business_label, owner_label


def telegram_is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_CHAT_ID and PUBLIC_BASE_URL)


def _telegram_request(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = urlencode(payload).encode("utf-8")
    request = Request(url, data=data, method="POST")

    try:
        return request_json_with_retries(request, timeout=20)
    except RuntimeError as exc:
        return {
            "ok": False,
            "telegram_error": str(exc),
        }


def send_owner_approval_request(
    lead_id: str,
    lead_name: str,
    company: str,
    recommendation: str,
    summary: str,
    classification: str = "",
    fit: str = "",
    urgency: str = "",
    score: int | float | str = "",
    draft_subject: str = "",
    draft_body: str = "",
) -> dict[str, Any]:
    if not telegram_is_configured():
        return {"configured": False}

    text = build_owner_approval_message(
        lead_id=lead_id,
        lead_name=lead_name,
        company=company,
        recommendation=recommendation,
        summary=summary,
        classification=classification,
        fit=fit,
        urgency=urgency,
        score=score,
        draft_subject=draft_subject,
        draft_body=draft_body,
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Approve",
                    "callback_data": f"approve:{lead_id}",
                },
                {
                    "text": "❌ Reject",
                    "callback_data": f"reject:{lead_id}",
                },
            ]
        ]
    }

    return _telegram_request(
        "sendMessage",
        {
            "chat_id": TELEGRAM_OWNER_CHAT_ID,
            "text": text,
            "reply_markup": json.dumps(reply_markup),
            "disable_web_page_preview": True,
        },
    )


def send_owner_status_notification(
    lead_id: str,
    lead_name: str,
    company: str,
    status: str,
    summary: str,
    classification: str = "",
    fit: str = "",
    urgency: str = "",
    score: int | float | str = "",
    draft_subject: str = "",
    draft_body: str = "",
) -> dict[str, Any]:
    if not telegram_is_configured():
        return {"configured": False}

    text = build_owner_status_message(
        lead_id=lead_id,
        lead_name=lead_name,
        company=company,
        status=status,
        summary=summary,
        classification=classification,
        fit=fit,
        urgency=urgency,
        score=score,
        draft_subject=draft_subject,
        draft_body=draft_body,
    )

    return _telegram_request(
        "sendMessage",
        {
            "chat_id": TELEGRAM_OWNER_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def send_owner_channel_escalation(
    *,
    lead_id: str,
    source_channel: str,
    sender_name: str,
    channel_user_id: str,
    owner_summary: str,
    qualification_summary: str,
    fit: str,
    urgency: str,
    score: int | float | str,
    extracted_profile: dict[str, Any],
    transcript: list[dict[str, Any]],
) -> dict[str, Any]:
    if not telegram_is_configured():
        return {"configured": False}

    text = build_owner_channel_escalation_message(
        lead_id=lead_id,
        source_channel=source_channel,
        sender_name=sender_name,
        channel_user_id=channel_user_id,
        owner_summary=owner_summary,
        qualification_summary=qualification_summary,
        fit=fit,
        urgency=urgency,
        score=score,
        extracted_profile=extracted_profile,
        transcript=transcript,
    )

    return _telegram_request(
        "sendMessage",
        {
            "chat_id": TELEGRAM_OWNER_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def build_owner_approval_message(
    lead_id: str,
    lead_name: str,
    company: str,
    recommendation: str,
    summary: str,
    classification: str = "",
    fit: str = "",
    urgency: str = "",
    score: int | float | str = "",
    draft_subject: str = "",
    draft_body: str = "",
) -> str:
    score_text = str(score) if score != "" else "not scored"
    draft_preview = _truncate(
        draft_body.strip() if draft_body else "No draft body found yet.",
        limit=1500,
    )

    return "\n".join(
        [
            f"🔔 Lead approval needed for {business_label()}",
            f"Owner: {owner_label()}",
            "",
            f"Lead: {lead_name or 'Unknown'}",
            f"Company: {company or 'Unknown'}",
            f"Lead ID: {lead_id}",
            "",
            "📌 Decision snapshot",
            f"- Classification: {classification or 'unknown'}",
            f"- Fit: {fit or 'unknown'}",
            f"- Urgency: {urgency or 'unknown'}",
            f"- Score: {score_text}",
            f"- Recommended action: {recommendation or 'review'}",
            "",
            "🧾 Owner summary",
            summary or "Review the drafted follow-up before customer-facing send.",
            "",
            "✉️ Draft email preview",
            f"Subject: {draft_subject or 'No subject found'}",
            "",
            draft_preview,
            "",
            "Tap Approve or Reject below.",
        ]
    )


def build_owner_channel_escalation_message(
    *,
    lead_id: str,
    source_channel: str,
    sender_name: str,
    channel_user_id: str,
    owner_summary: str,
    qualification_summary: str,
    fit: str,
    urgency: str,
    score: int | float | str,
    extracted_profile: dict[str, Any],
    transcript: list[dict[str, Any]],
) -> str:
    profile_lines = [
        f"- {key}: {value}"
        for key, value in sorted(extracted_profile.items())
        if value
    ]
    transcript_lines = [
        f"{str(item.get('role', 'unknown')).title()}: {item.get('content', '')}"
        for item in transcript[-8:]
    ]

    return "\n".join(
        [
            f"🔥 Qualified messaging lead for {business_label()}",
            f"Owner: {owner_label()}",
            "",
            f"Lead ID: {lead_id}",
            f"Channel: {source_channel}",
            f"Sender: {sender_name or 'Unknown'}",
            f"Channel user id: {channel_user_id}",
            "",
            "📌 Decision snapshot",
            f"- Fit: {fit or 'unknown'}",
            f"- Urgency: {urgency or 'unknown'}",
            f"- Score: {score if score != '' else 'not scored'}",
            "",
            "🧾 Owner summary",
            owner_summary or "The conversation needs owner review.",
            "",
            "🎯 Qualification summary",
            qualification_summary or "No qualification summary was returned.",
            "",
            "👤 Extracted profile",
            "\n".join(profile_lines) if profile_lines else "No profile fields extracted yet.",
            "",
            "💬 Recent transcript",
            _truncate("\n".join(transcript_lines), limit=1500)
            if transcript_lines
            else "No transcript found.",
        ]
    )


def build_owner_status_message(
    lead_id: str,
    lead_name: str,
    company: str,
    status: str,
    summary: str,
    classification: str = "",
    fit: str = "",
    urgency: str = "",
    score: int | float | str = "",
    draft_subject: str = "",
    draft_body: str = "",
) -> str:
    score_text = str(score) if score != "" else "not scored"
    draft_preview = _truncate(
        draft_body.strip() if draft_body else "No draft body found yet.",
        limit=1200,
    )

    return "\n".join(
        [
            f"⚡ Lead processed for {business_label()}: {status}",
            f"Owner: {owner_label()}",
            "",
            f"Lead: {lead_name or 'Unknown'}",
            f"Company: {company or 'Unknown'}",
            f"Lead ID: {lead_id}",
            "",
            "📌 Decision snapshot",
            f"- Classification: {classification or 'unknown'}",
            f"- Fit: {fit or 'unknown'}",
            f"- Urgency: {urgency or 'unknown'}",
            f"- Score: {score_text}",
            "",
            "🧾 Owner summary",
            summary or "The lead workflow finished.",
            "",
            "✉️ Message preview",
            f"Subject: {draft_subject or 'No subject found'}",
            "",
            draft_preview,
        ]
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...\n\n[Preview truncated. Full draft is saved in Airtable and outputs.]"


def answer_callback_query(callback_query_id: str, text: str) -> dict[str, Any]:
    return _telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_query_id,
            "text": text,
        },
    )


def edit_approval_message(
    chat_id: int | str,
    message_id: int,
    text: str,
) -> dict[str, Any]:
    return _telegram_request(
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": json.dumps({"inline_keyboard": []}),
        },
    )
    
    
def remove_approval_buttons(
    chat_id: int | str,
    message_id: int,
) -> dict[str, Any]:
    return _telegram_request(
        "editMessageReplyMarkup",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": json.dumps({"inline_keyboard": []}),
        },
    )
