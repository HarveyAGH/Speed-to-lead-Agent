from __future__ import annotations

import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from langgraph.errors import GraphInterrupt

from config import (
    MAX_WEBHOOK_BODY_BYTES,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    AGENCY_PROFILE_PATH,
    TELEGRAM_ALLOW_OWNER_AS_LEAD,
    TELEGRAM_WEBHOOK_SECRET,
    WEBHOOK_SHARED_SECRET,
    OWNER_CONFIG_PATH,
)
from langgraph.types import Command
from channels.channel_dispatcher import dispatch_lead_response
from channels.whatsapp.adapter import register_whatsapp
from tools.airtable_client import (
    airtable_is_configured,
    find_latest_agent_run_by_lead_id,
    update_lead_fields,
    update_latest_agent_run_status,
)
from tools.channel_conversations import mark_conversation_owner_action
from tools.lead_ingestion import build_lead_fingerprint, ingest_lead
from tools.job_queue import (
    get_job_payload_by_lead_id,
    list_recent_jobs,
    mark_latest_job_status_by_lead_id,
    mark_latest_waiting_job_resolved,
    queue_is_configured,
)
from tools.owner_config import get_owner_config

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
    return resume_lead_send(lead_id, "approve")


@app.post("/approval/{lead_id}/reject")
def reject_lead_send(
    lead_id: str,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_management_secret(x_webhook_secret)
    return resume_lead_send(lead_id, "reject")


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

    latest_run = _latest_agent_run_fields(lead_id)
    current_status = str(latest_run.get("approval_status") or "")
    if current_status in {"approved_sent", "rejected_by_owner"}:
        decision_label = "already approved ✅" if current_status == "approved_sent" else "already rejected ❌"
        if acknowledge:
            answer_callback_query(callback_id, f"Lead was {decision_label}.")
        edit_result = None
        if chat_id and message_id:
            remove_approval_buttons(chat_id=chat_id, message_id=message_id)
            edit_result = edit_approval_message(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    f"Lead {lead_id} {decision_label}\n\n"
                    "This approval decision had already been processed."
                ),
            )
        return {
            "ok": True,
            "lead_id": lead_id,
            "decision": decision,
            "status": "duplicate_callback_ignored",
            "telegram_edit": edit_result,
        }

    if acknowledge:
        answer_callback_query(callback_id, f"{decision.title()} received. Processing...")
    if acknowledge and chat_id and message_id:
        remove_approval_buttons(chat_id=chat_id, message_id=message_id)

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

    if dispatch_failed:
        approval_status = "approved_dispatch_failed"
    else:
        approval_status = "approved_sent" if decision == "approve" else "rejected_by_owner"
    airtable_status_update = update_latest_agent_run_status(
        lead_id=lead_id,
        approval_status=approval_status,
    )
    queue_status_update = mark_latest_waiting_job_resolved(
        lead_id=lead_id,
        status=approval_status,
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

    latest_run = _latest_agent_run_fields(lead_id)
    current_status = str(latest_run.get("approval_status") or "")
    if current_status in {"approved_sent", "rejected_by_owner"}:
        return _process_form_approval_callback(callback, acknowledge=True)

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
        "lead_id": _sanitize_lead_value(lead_id, limit=120),
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


def _latest_agent_run_fields(lead_id: str) -> dict[str, Any]:
    try:
        record = find_latest_agent_run_by_lead_id(lead_id)
    except Exception:
        return {}

    if not record:
        return {}
    return dict(record.get("fields", {}))


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


def _owner_summary_from_run(run_fields: dict[str, Any]) -> str:
    if not run_fields:
        return (
            "The agent processed this lead and paused before customer-facing send. "
            "Review the draft before approving or rejecting."
        )

    classification = run_fields.get("classification") or "unknown"
    fit = run_fields.get("fit") or "unknown"
    urgency = run_fields.get("urgency") or "unknown"
    score = run_fields.get("score") or "not scored"
    action = run_fields.get("recommended_next_action") or "review"

    return (
        f"The agent classified this lead as {classification} with {fit} fit, "
        f"{urgency} urgency, and score {score}. Recommended action: {action}. "
        "Review the draft before approving the customer-facing follow-up."
    )


def _graph_interrupt_summary(exc: GraphInterrupt) -> str:
    return (
        "The workflow paused at a human approval boundary. "
        f"Interrupt detail: {exc}"
    )


def run_approval_workflow(lead_id: str) -> str:
    return run_approval_workflow_status(lead_id)["summary"]


def run_approval_workflow_status(lead_id: str) -> dict[str, Any]:
    from graph import graph

    config = build_trace_config(
        lead_id=lead_id,
        phase="initial",
        source="tally",
        tags=["webhook", "tally", "lead_intake", "pipeline"],
    )
    result = graph.invoke(
        {"lead_id": lead_id},
        config=config,
    )

    if "__interrupt__" in result:
        return {
            "status": "pending_approval",
            "summary": (
                "The workflow paused at a human approval boundary. "
                f"Interrupt detail: {result['__interrupt__']}"
            ),
            "interrupt": result["__interrupt__"],
        }

    return {
        "status": "completed",
        "summary": result.get("summary", "Workflow Completed."),
        "interrupt": None,
        "state": result,
    }


def resume_lead_send(lead_id: str, decision: str) -> dict[str, Any]:
    from graph import graph

    config = build_trace_config(
        lead_id=lead_id,
        phase=f"approval.{decision}",
        source="telegram",
        tags=["approval", "telegram", "lead_intake", "pipeline"],
        metadata={"decision": decision},
    )

    result = graph.invoke(Command(resume=decision), config=config)

    return {
        "status": decision,
        "lead_id": lead_id,
        "result": result.get("summary", "Workflow resumed."),
        "state": result,
    }


def build_trace_config(
    *,
    lead_id: str,
    phase: str,
    source: str,
    tags: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thread_id = f"lead-{lead_id}"
    base_metadata = {
        "lead_id": lead_id,
        "thread_id": thread_id,
        "source": source,
        "workflow": "speed_to_lead",
        "workflow_phase": phase,
        "workflow_architecture": "explicit_stategraph",
        "checkpoint_backend": "postgres",
    }
    if metadata:
        base_metadata.update(metadata)

    return {
        "configurable": {
            "thread_id": thread_id,
        },
        "run_name": f"speed_to_lead.{phase}.{lead_id}",
        "tags": tags,
        "metadata": base_metadata,
    }
