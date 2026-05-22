from __future__ import annotations

import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from config import (
    ALLOW_INSECURE_LOCAL_WEBHOOKS,
    MAX_WEBHOOK_BODY_BYTES,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    AGENCY_PROFILE_PATH,
    EMAIL_TRANSPORT,
    RESEND_API_KEY,
    RESEND_FROM_EMAIL,
    RESEND_REPLY_TO_EMAIL,
    TELEGRAM_ALLOW_OWNER_AS_LEAD,
    TELEGRAM_WEBHOOK_SECRET,
    WEBHOOK_SHARED_SECRET,
    OWNER_CONFIG_PATH,
)
from channels.channel_dispatcher import dispatch_lead_response
from channels.whatsapp.adapter import register_whatsapp
from tools.airtable_client import (
    airtable_is_configured,
    update_lead_fields,
    update_latest_agent_run_status,
)
from tools.channel_conversations import mark_conversation_owner_action
from tools.lead_ingestion import build_lead_fingerprint, ingest_lead
from tools.job_queue import (
    claim_waiting_approval_job,
    get_job_payload_by_lead_id,
    list_recent_jobs,
    mark_lead_job_completed,
    mark_lead_job_failed,
    mark_latest_job_status_by_lead_id,
    queue_is_configured,
)
from tools.owner_config import get_owner_config
from tools.io_helpers import safe_path_component
from tools.workflow_runner import (
    latest_agent_run_fields,
    resume_lead_send,
    run_approval_workflow_status,
)

from tools.telegram import (
    answer_callback_query,
    edit_approval_message,
    remove_approval_buttons,
    telegram_is_configured,
)



@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    validate_startup_config()
    yield


app = FastAPI(title="Lead Intake Agent API", lifespan=lifespan)
_rate_limit_windows: dict[str, deque[float]] = defaultdict(deque)
logger = logging.getLogger("lead_api")
register_whatsapp(app)


def validate_startup_config() -> None:
    if not AGENCY_PROFILE_PATH.exists():
        raise RuntimeError(f"AGENCY_PROFILE_PATH not found: {AGENCY_PROFILE_PATH}")
    if not OWNER_CONFIG_PATH.exists():
        logger.warning(
            "OWNER_CONFIG_PATH not found: %s — owner defaults may be incomplete",
            OWNER_CONFIG_PATH,
        )
    if not WEBHOOK_SHARED_SECRET and not ALLOW_INSECURE_LOCAL_WEBHOOKS:
        raise RuntimeError(
            "WEBHOOK_SHARED_SECRET is required. Set "
            "ALLOW_INSECURE_LOCAL_WEBHOOKS=true only for local development."
        )
    if EMAIL_TRANSPORT not in {"simulated", "resend"}:
        raise RuntimeError(
            "Unsupported EMAIL_TRANSPORT. Use EMAIL_TRANSPORT=simulated or "
            "EMAIL_TRANSPORT=resend."
        )
    if EMAIL_TRANSPORT == "resend":
        missing = [
            name
            for name, value in (
                ("RESEND_API_KEY", RESEND_API_KEY),
                ("RESEND_FROM_EMAIL", RESEND_FROM_EMAIL),
                ("RESEND_REPLY_TO_EMAIL", RESEND_REPLY_TO_EMAIL),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "EMAIL_TRANSPORT=resend requires: " + ", ".join(missing)
            )


@app.middleware("http")
async def request_guardrails(request: Request, call_next):
    if request.method == "POST" and _is_guarded_path(request.url.path):
        # Advisory only: chunked requests can omit content-length. Enforce the
        # same body-size limit at the reverse proxy before production deploy.
        content_length = request.headers.get("content-length")
        if (
            content_length
            and _safe_int(content_length) > MAX_WEBHOOK_BODY_BYTES
        ):
            return JSONResponse(
                status_code=413,
                content={
                    "detail": (
                        f"Request body too large. Limit is {MAX_WEBHOOK_BODY_BYTES} bytes."
                    )
                },
            )

        if _is_rate_limited(request):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Try again shortly."},
            )

    return await call_next(request)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "airtable_configured": airtable_is_configured(),
        "queue_configured": queue_is_configured(),
        "telegram_configured": telegram_is_configured(),
        "telegram_webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
        "owner_config": {
            "owner_name": get_owner_config().get("owner_name"),
            "business_name": get_owner_config().get("business_name"),
            "approval_channel": get_owner_config().get("approval_channel"),
        },
    }


@app.get("/jobs")
def recent_jobs(limit: int = 10) -> dict[str, Any]:
    return {"jobs": list_recent_jobs(limit=limit)}


@app.post("/webhooks/tally")
def tally_webhook(
    payload: dict[str, Any],
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    if WEBHOOK_SHARED_SECRET and x_webhook_secret != WEBHOOK_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    lead = normalize_lead_payload(payload)
    result = ingest_lead(lead)
    if result.get("status") == "error":
        raise HTTPException(
            status_code=int(result.get("http_status") or 500),
            detail=str(result.get("error") or "Lead ingestion failed"),
        )

    logger.info(
        "tally_webhook status=%s lead_id=%s job_id=%s duplicate_of=%s",
        result.get("status"),
        lead["lead_id"],
        (result.get("job") or {}).get("id"),
        (result.get("duplicate_of") or {}).get("lead_id"),
    )
    return result


@app.post("/approval/{lead_id}/approve")
def approve_lead_send(
    lead_id: str,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_management_secret(x_webhook_secret)
    return _resume_claimed_management_approval(lead_id, "approve")


@app.post("/approval/{lead_id}/reject")
def reject_lead_send(
    lead_id: str,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_management_secret(x_webhook_secret)
    return _resume_claimed_management_approval(lead_id, "reject")


@app.post("/telegram/webhook")
def telegram_webhook_route(
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, Any]:
    return telegram_webhook(
        payload,
        x_telegram_bot_api_secret_token=x_telegram_bot_api_secret_token,
        background_tasks=background_tasks,
    )


def telegram_webhook(
    payload: dict[str, Any],
    x_telegram_bot_api_secret_token: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    if (
        TELEGRAM_WEBHOOK_SECRET
        and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    callback = payload.get("callback_query")
    if callback:
        if background_tasks is not None and _is_form_approval_callback(callback):
            return _queue_form_approval_callback(callback, background_tasks)
        return _handle_owner_callback(callback)

    message = payload.get("message")
    if message:
        from channels.telegram_leads.adapter import (
            handle_telegram_lead_message,
            is_owner_chat,
        )
        from tools.inbound_events import record_inbound_event

        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        chat_id = str(chat.get("id") or from_user.get("id") or "")
        if chat_id and (TELEGRAM_ALLOW_OWNER_AS_LEAD or not is_owner_chat(chat_id)):
            telegram_event_id = _telegram_message_event_id(payload, message)
            if telegram_event_id and not record_inbound_event(
                "telegram",
                telegram_event_id,
            ):
                logger.info(
                    "telegram_lead_duplicate_ignored event_id=%s chat_id=%s",
                    telegram_event_id,
                    chat_id,
                )
                return {"ok": True, "duplicate_ignored": telegram_event_id}

            result = handle_telegram_lead_message(message)
            logger.info(
                "telegram_lead_update status=%s lead_id=%s",
                result.get("status"),
                result.get("lead_id"),
            )
            return {"ok": True, "lead_intake": result}

        return {"ok": True, "ignored": "owner_chat_or_missing_chat"}

    return {"ok": True, "ignored": "unsupported_telegram_update"}


def _handle_owner_callback(callback: dict[str, Any]) -> dict[str, Any]:
    callback_id = callback["id"]
    data = callback.get("data", "")
    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    message_id = message.get("message_id")

    if ":" not in data:
        answer_callback_query(callback_id, "Invalid approval action.")
        return {"ok": False, "error": "invalid_callback_data"}

    if data.startswith("channel:"):
        return _handle_channel_owner_action(
            callback_id=callback_id,
            data=data,
            chat_id=chat_id,
            message_id=message_id,
        )

    return _process_form_approval_callback(callback, acknowledge=True)


def _resume_claimed_management_approval(lead_id: str, decision: str) -> dict[str, Any]:
    claimed_job = claim_waiting_approval_job(lead_id, decision)
    if not claimed_job:
        return {
            "ok": True,
            "lead_id": lead_id,
            "decision": decision,
            "status": "duplicate_callback_ignored",
            "reason": "approval_job_already_claimed_or_processed",
        }

    try:
        result = resume_lead_send(lead_id, decision)
    except Exception as exc:
        logger.error(
            "management_approval_resume_failed lead_id=%s job_id=%s decision=%s error=%s",
            lead_id,
            claimed_job["id"],
            decision,
            str(exc),
            exc_info=True,
        )
        queue_failure = mark_lead_job_failed(int(claimed_job["id"]), str(exc))
        return {
            "ok": False,
            "lead_id": lead_id,
            "decision": decision,
            "status": "approval_resume_failed",
            "error": str(exc),
            "queue_status_update": queue_failure,
        }

    approval_status = "approved_sent" if decision == "approve" else "rejected_by_owner"
    airtable_status_update = update_latest_agent_run_status(
        lead_id=lead_id,
        approval_status=approval_status,
    )
    queue_status_update = mark_lead_job_completed(
        int(claimed_job["id"]),
        status=approval_status,
        first_response=approval_status == "approved_sent",
    )

    return {
        "ok": True,
        "lead_id": lead_id,
        "decision": decision,
        "result": result,
        "airtable_status_update": airtable_status_update,
        "queue_status_update": queue_status_update,
    }


def _process_form_approval_callback(
    callback: dict[str, Any],
    *,
    acknowledge: bool,
) -> dict[str, Any]:
    callback_id = callback["id"]
    data = callback.get("data", "")
    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    message_id = message.get("message_id")

    if ":" not in data:
        if acknowledge:
            answer_callback_query(callback_id, "Invalid approval action.")
        return {"ok": False, "error": "invalid_callback_data"}

    decision, lead_id = data.split(":", 1)

    if decision not in {"approve", "reject"}:
        if acknowledge:
            answer_callback_query(callback_id, "Unknown decision.")
        return {"ok": False, "error": "unknown_decision"}

    claimed_job = claim_waiting_approval_job(lead_id, decision)
    if not claimed_job:
        decision_label = "already claimed or processed"
        if acknowledge:
            answer_callback_query(callback_id, f"Lead was {decision_label}.")
        edit_result = None
        if chat_id and message_id:
            remove_approval_buttons(chat_id=chat_id, message_id=message_id)
            edit_result = edit_approval_message(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    f"Lead {lead_id}: approval already claimed or processed.\n\n"
                    "No duplicate workflow resume was started."
                ),
            )
        return {
            "ok": True,
            "lead_id": lead_id,
            "decision": decision,
            "status": "duplicate_callback_ignored",
            "reason": "approval_job_already_claimed_or_processed",
            "telegram_edit": edit_result,
        }

    latest_run = latest_agent_run_fields(lead_id)
    if acknowledge:
        answer_callback_query(callback_id, f"{decision.title()} received. Processing...")
    if acknowledge and chat_id and message_id:
        remove_approval_buttons(chat_id=chat_id, message_id=message_id)

    try:
        result = resume_lead_send(lead_id, decision)
        channel_dispatch_result = None
        if decision == "approve":
            channel_dispatch_result = _dispatch_approved_response(
                lead_id=lead_id,
                latest_run=latest_run,
            )
        dispatch_failed = (
            decision == "approve"
            and channel_dispatch_result is not None
            and channel_dispatch_result.get("ok") is False
        )
    except Exception as exc:
        logger.error(
            "approval_resume_failed lead_id=%s job_id=%s decision=%s error=%s",
            lead_id,
            claimed_job["id"],
            decision,
            str(exc),
            exc_info=True,
        )
        queue_failure = mark_lead_job_failed(int(claimed_job["id"]), str(exc))
        if chat_id and message_id:
            edit_approval_message(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    f"Lead {lead_id}: approval processing failed.\n\n"
                    "The queue job was released for retry."
                ),
            )
        return {
            "ok": False,
            "lead_id": lead_id,
            "decision": decision,
            "status": "approval_resume_failed",
            "error": str(exc),
            "queue_status_update": queue_failure,
        }

    if dispatch_failed:
        approval_status = "approved_dispatch_failed"
    else:
        approval_status = "approved_sent" if decision == "approve" else "rejected_by_owner"
    airtable_status_update = update_latest_agent_run_status(
        lead_id=lead_id,
        approval_status=approval_status,
    )
    queue_status_update = mark_lead_job_completed(
        int(claimed_job["id"]),
        status=approval_status,
        first_response=approval_status == "approved_sent",
    )

    if dispatch_failed:
        decision_label = "approved, but channel send failed ⚠️"
    else:
        decision_label = "approved ✅" if decision == "approve" else "rejected ❌"
    edit_result = None
    if chat_id and message_id:
        edit_result = edit_approval_message(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"Lead {lead_id} {decision_label}\n\n"
                "The approval decision has been processed."
            ),
        )

    return {
        "ok": True,
        "lead_id": lead_id,
        "decision": decision,
        "result": result,
        "channel_dispatch": channel_dispatch_result,
        "telegram_edit": edit_result,
        "airtable_status_update": airtable_status_update,
        "queue_status_update": queue_status_update,
    }


def _is_form_approval_callback(callback: dict[str, Any]) -> bool:
    data = str(callback.get("data") or "")
    return data.startswith("approve:") or data.startswith("reject:")


def _queue_form_approval_callback(
    callback: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    callback_id = callback["id"]
    data = str(callback.get("data") or "")
    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    message_id = message.get("message_id")

    if ":" not in data:
        answer_callback_query(callback_id, "Invalid approval action.")
        return {"ok": False, "error": "invalid_callback_data"}

    decision, lead_id = data.split(":", 1)
    if decision not in {"approve", "reject"}:
        answer_callback_query(callback_id, "Unknown decision.")
        return {"ok": False, "error": "unknown_decision"}

    answer_callback_query(callback_id, f"{decision.title()} received. Processing...")
    if chat_id and message_id:
        remove_approval_buttons(chat_id=chat_id, message_id=message_id)
        edit_approval_message(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"Lead {lead_id}: {decision} received.\n\n"
                "Processing the approval decision now."
            ),
        )

    background_tasks.add_task(
        _process_form_approval_callback,
        callback,
        acknowledge=False,
    )
    return {
        "ok": True,
        "lead_id": lead_id,
        "decision": decision,
        "status": "queued_for_processing",
    }


def _handle_channel_owner_action(
    *,
    callback_id: str,
    data: str,
    chat_id: int | str | None,
    message_id: int | None,
) -> dict[str, Any]:
    parts = data.split(":", 2)
    if len(parts) != 3:
        answer_callback_query(callback_id, "Invalid owner action.")
        return {"ok": False, "error": "invalid_channel_action"}

    _, action, lead_id = parts
    if action not in {"take_over", "mark_booked", "mark_not_fit"}:
        answer_callback_query(callback_id, "Unknown owner action.")
        return {"ok": False, "error": "unknown_channel_action"}

    status = _channel_owner_action_status(action)
    answer_callback_query(callback_id, _channel_owner_action_toast(action))

    conversation_update = mark_conversation_owner_action(
        lead_id=lead_id,
        action=action,
    )
    queue_update = mark_latest_job_status_by_lead_id(
        lead_id=lead_id,
        status=status,
    )
    airtable_update = update_lead_fields(
        lead_id=lead_id,
        fields={"status": status},
    )

    edit_result = None
    if chat_id and message_id:
        edit_result = edit_approval_message(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"Lead {lead_id}: {_channel_owner_action_confirmation(action)}\n\n"
                "The owner action has been recorded."
            ),
        )

    return {
        "ok": True,
        "lead_id": lead_id,
        "action": action,
        "status": status,
        "conversation_update": conversation_update,
        "queue_update": queue_update,
        "airtable_update": airtable_update,
        "telegram_edit": edit_result,
    }


def _telegram_message_event_id(
    payload: dict[str, Any],
    message: dict[str, Any],
) -> str:
    update_id = payload.get("update_id")
    if update_id is not None:
        return f"update:{update_id}"

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is not None and message_id is not None:
        return f"message:{chat_id}:{message_id}"

    return ""


def _channel_owner_action_status(action: str) -> str:
    return {
        "take_over": "owner_taking_over",
        "mark_booked": "owner_marked_booked",
        "mark_not_fit": "owner_marked_not_fit",
    }[action]


def _channel_owner_action_toast(action: str) -> str:
    return {
        "take_over": "Take over recorded.",
        "mark_booked": "Lead marked booked.",
        "mark_not_fit": "Lead marked not fit.",
    }[action]


def _channel_owner_action_confirmation(action: str) -> str:
    return {
        "take_over": "owner is taking over ✅",
        "mark_booked": "marked booked 📅",
        "mark_not_fit": "marked not fit ❌",
    }[action]


def normalize_lead_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Convert either a flat JSON body or a Tally-style body into lead fields."""
    fields = _extract_tally_fields(payload) if "data" in payload else payload

    lead_id = str(fields.get("lead_id") or f"lead_{uuid4().hex[:8]}")
    return {
        "lead_id": safe_path_component(
            _sanitize_lead_value(lead_id, limit=120),
            fallback="lead",
            limit=120,
        ),
        "received_at": _sanitize_lead_value(fields.get("received_at"), limit=120),
        "name": _sanitize_lead_value(fields.get("name"), limit=200),
        "email": _sanitize_lead_value(fields.get("email"), limit=254),
        "company": _sanitize_lead_value(fields.get("company"), limit=200),
        "role": _sanitize_lead_value(fields.get("role"), limit=120),
        "source": _sanitize_lead_value(fields.get("source") or "website_form", limit=80),
        "service_interest": _sanitize_lead_value(fields.get("service_interest"), limit=300),
        "message": _sanitize_lead_value(fields.get("message"), limit=2000),
        "budget": _sanitize_lead_value(fields.get("budget"), limit=120),
        "timeline": _sanitize_lead_value(fields.get("timeline"), limit=120),
        "website": _sanitize_lead_value(fields.get("website"), limit=300),
        "status": _sanitize_lead_value(fields.get("status") or "new", limit=80),
    }


def _extract_tally_fields(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    raw_fields = data.get("fields") or []
    fields: dict[str, Any] = {}

    submission_id = data.get("responseId") or data.get("submissionId") or data.get("id")
    if submission_id:
        fields["lead_id"] = f"lead_{submission_id}"

    created_at = data.get("createdAt") or data.get("submittedAt")
    if created_at:
        fields["received_at"] = created_at

    for item in raw_fields:
        key = _normalize_field_name(item.get("label") or item.get("key"))
        value = item.get("value")
        if key:
            fields[key] = value

    return fields


def _normalize_field_name(name: Any) -> str:
    if not name:
        return ""

    normalized = str(name).strip().lower().replace("-", " ").replace("_", " ")
    aliases = {
        "lead id": "lead_id",
        "received at": "received_at",
        "name": "name",
        "full name": "name",
        "email": "email",
        "email address": "email",
        "company": "company",
        "company name": "company",
        "role": "role",
        "job title": "role",
        "source": "source",
        "service interest": "service_interest",
        "what service are you interested in": "service_interest",
        "message": "message",
        "budget": "budget",
        "timeline": "timeline",
        "website": "website",
        "status": "status",
    }
    return aliases.get(normalized, "")


def _sanitize_lead_value(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    cleaned = "".join(
        char if char in {"\n", "\t"} or ord(char) >= 32 else " "
        for char in text
    )
    return cleaned.strip()[:limit]


def _require_management_secret(secret: str | None) -> None:
    if not WEBHOOK_SHARED_SECRET or secret != WEBHOOK_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _is_guarded_path(path: str) -> bool:
    return (
        path == "/webhooks/tally"
        or path == "/telegram/webhook"
        or path == "/whatsapp/webhook"
        or path.startswith("/approval/")
    )


def _is_rate_limited(request: Request) -> bool:
    if RATE_LIMIT_REQUESTS <= 0 or RATE_LIMIT_WINDOW_SECONDS <= 0:
        return False

    client_host = request.client.host if request.client else "unknown"
    key = f"{client_host}:{request.url.path}"
    now = monotonic()
    window = _rate_limit_windows[key]

    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()

    if len(window) >= RATE_LIMIT_REQUESTS:
        return True

    window.append(now)
    return False


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _dispatch_approved_response(
    *,
    lead_id: str,
    latest_run: dict[str, Any],
) -> dict[str, Any] | None:
    payload = get_job_payload_by_lead_id(lead_id)
    source_channel = str(payload.get("source_channel") or "")
    channel_user_id = str(payload.get("channel_user_id") or "")
    if not source_channel or not channel_user_id:
        return None

    return dispatch_lead_response(
        source_channel=source_channel,
        channel_user_id=channel_user_id,
        subject=str(latest_run.get("draft_subject") or ""),
        body=str(latest_run.get("draft_body") or ""),
    )
