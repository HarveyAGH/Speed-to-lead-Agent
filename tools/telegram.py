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
            "reply_markup": json.dumps(build_channel_owner_action_markup(lead_id)),
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
        limit=850,
    )
    lead_title = _lead_title(lead_name=lead_name, company=company)
    headline = _headline_for_fit(
        fit=fit,
        urgency=urgency,
        score=score_text,
        fallback="Review this lead before sending",
    )

    return _compact_message(
        [
            f"⚡ {headline}",
            f"{lead_title} · {business_label()}",
            "",
            "📌 Snapshot",
            _inline_fields(
                ("Lead", lead_name or "Unknown"),
                ("Company", company or "Unknown"),
                ("Fit", fit or "unknown"),
                ("Urgency", urgency or "unknown"),
                ("Score", score_text),
            ),
            "",
            "🧠 Why now",
            summary or "Review the drafted follow-up before customer-facing send.",
            "",
            "✉️ Draft preview",
            _format_field("Subject", draft_subject or "No subject found"),
            "",
            draft_preview,
            "",
            "✅ Approve if this should go out. Reject if it needs manual review.",
            _format_field("Lead ID", lead_id),
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
    profile_lines = _profile_lines(extracted_profile)
    customer_preview = _latest_customer_message(transcript)
    transcript_lines = _transcript_lines(transcript[-4:])
    lead_label = _best_profile_value(
        extracted_profile,
        "company_name",
        "business_type",
        default=sender_name or "Messaging lead",
    )
    headline = _headline_for_fit(
        fit=fit,
        urgency=urgency,
        score=score,
        fallback="Qualified messaging lead",
    )

    return _compact_message(
        [
            f"🔥 {headline}",
            f"{lead_label} · {source_channel}",
            "",
            "💬 Customer said",
            customer_preview or "No recent customer message found.",
            "",
            "📌 Snapshot",
            _inline_fields(
                ("Fit", fit or "unknown"),
                ("Urgency", urgency or "unknown"),
                ("Score", score if score != "" else "not scored"),
                ("Channel", source_channel),
            ),
            "",
            "🧠 Why this matters",
            owner_summary or "The conversation needs owner review.",
            "",
            "🎯 Key details",
            "\n".join(profile_lines[:6]) if profile_lines else "No profile fields extracted yet.",
            "",
            "🧾 Recent context",
            _truncate("\n".join(transcript_lines), limit=650)
            if transcript_lines
            else "No transcript found.",
            "",
            "🚀 Suggested move",
            qualification_summary
            or "Reach out while the lead is warm. The AI already set the expectation that a human will follow up.",
            "",
            _format_field("Lead ID", lead_id),
            _format_field("User", channel_user_id),
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
        limit=750,
    )
    lead_title = _lead_title(lead_name=lead_name, company=company)
    headline = _status_headline(status)

    return _compact_message(
        [
            f"⚡ {headline}",
            f"{lead_title} · {business_label()}",
            "",
            "📌 Snapshot",
            _inline_fields(
                ("Lead", lead_name or "Unknown"),
                ("Company", company or "Unknown"),
                ("Fit", fit or "unknown"),
                ("Urgency", urgency or "unknown"),
                ("Score", score_text),
            ),
            "",
            "🧠 Owner summary",
            summary or "The lead workflow finished.",
            "",
            "✉️ Customer-facing message",
            _format_field("Subject", draft_subject or "No subject found"),
            "",
            draft_preview,
            "",
            _format_field("Lead ID", lead_id),
        ]
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...\n\n[Preview truncated. Full draft is saved in Airtable and outputs.]"


def _compact_message(lines: list[str], *, limit: int = 3900) -> str:
    text = "\n".join(str(line).rstrip() for line in lines).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...\n\n[Telegram preview truncated. Full details are stored in the run artifacts.]"


def _format_field(label: str, value: Any) -> str:
    return f"• {label}: {value}"


def _inline_fields(*items: tuple[str, Any]) -> str:
    return " · ".join(f"{label}: {value}" for label, value in items)


def _lead_title(*, lead_name: str, company: str) -> str:
    if lead_name and company:
        return f"{lead_name} at {company}"
    if company:
        return company
    if lead_name:
        return lead_name
    return "Unknown lead"


def _headline_for_fit(
    *,
    fit: str,
    urgency: str,
    score: int | float | str,
    fallback: str,
) -> str:
    fit_text = str(fit or "").lower()
    urgency_text = str(urgency or "").lower()
    score_number = _safe_float(score)

    if fit_text == "high" and (
        urgency_text in {"same_day", "this_week"} or score_number >= 80
    ):
        return "Hot lead ready for owner review"
    if fit_text == "high":
        return "Strong lead needs a quick look"
    if urgency_text in {"same_day", "this_week"}:
        return "Time-sensitive lead needs review"
    return fallback


def _status_headline(status: str) -> str:
    normalized = str(status or "").lower()
    if "auto" in normalized and "sent" in normalized:
        return "Safe first response sent"
    if "approved" in normalized or "sent" in normalized:
        return "Customer follow-up sent"
    if "reject" in normalized:
        return "Lead follow-up rejected"
    if "approval" in normalized or "review" in normalized:
        return "Lead waiting for review"
    return f"Lead processed: {status or 'completed'}"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _best_profile_value(
    profile: dict[str, Any],
    *keys: str,
    default: str,
) -> str:
    for key in keys:
        value = str(profile.get(key) or "").strip()
        if value and value != "<UNKNOWN>":
            return value
    return default


def _profile_lines(profile: dict[str, Any]) -> list[str]:
    priority = [
        "business_type",
        "company_name",
        "pain_point",
        "lead_volume",
        "current_tools",
        "service_interest",
        "budget",
        "timeline",
        "team_size",
        "website",
    ]
    lines: list[str] = []
    seen: set[str] = set()

    for key in priority:
        value = profile.get(key)
        if _is_meaningful_profile_value(value):
            lines.append(_format_field(_humanize_key(key), value))
            seen.add(key)

    for key, value in sorted(profile.items()):
        if key in seen or not _is_meaningful_profile_value(value):
            continue
        lines.append(_format_field(_humanize_key(key), value))
        if len(lines) >= 10:
            break

    return lines


def _is_meaningful_profile_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text != "<UNKNOWN>")


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").title()


def _latest_customer_message(transcript: list[dict[str, Any]]) -> str:
    for item in reversed(transcript):
        if str(item.get("role") or "").lower() == "customer":
            content = str(item.get("content") or "").strip()
            if content:
                return _truncate(f"“{content}”", limit=550)
    return ""


def _transcript_lines(transcript: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in transcript:
        role = str(item.get("role") or "unknown").strip().title()
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return lines


def build_channel_owner_action_markup(lead_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ I'm handling this",
                    "callback_data": f"channel:take_over:{lead_id}",
                },
                {
                    "text": "📅 Mark booked",
                    "callback_data": f"channel:mark_booked:{lead_id}",
                },
            ],
            [
                {
                    "text": "❌ Close as not fit",
                    "callback_data": f"channel:mark_not_fit:{lead_id}",
                },
            ],
        ]
    }


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
