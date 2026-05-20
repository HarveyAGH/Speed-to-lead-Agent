from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from langgraph.errors import GraphInterrupt

from config import (
    MAX_WEBHOOK_BODY_BYTES,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    TELEGRAM_WEBHOOK_SECRET,
    WEBHOOK_SHARED_SECRET,
)
from langgraph.types import Command
from tools.airtable_client import (
    airtable_is_configured,
    create_lead,
    find_lead_by_id,
    find_latest_agent_run_by_lead_id,
    update_latest_agent_run_status,
)
from tools.job_queue import (
    enqueue_lead_job,
    find_active_job_by_lead_id,
    list_recent_jobs,
    mark_latest_waiting_job_resolved,
    queue_is_configured,
)

from tools.telegram import (
    answer_callback_query,
    edit_approval_message,
    remove_approval_buttons,
    telegram_is_configured,
)


app = FastAPI(title="Lead Intake Agent API")
_rate_limit_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def request_guardrails(request: Request, call_next):
    if request.method == "POST" and _is_guarded_path(request.url.path):
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
    if not airtable_is_configured():
        raise HTTPException(status_code=500, detail="Airtable is not configured")
    if not queue_is_configured():
        raise HTTPException(status_code=500, detail="POSTGRES_DB_URI is required for queued processing")

    existing_lead = find_lead_by_id(lead["lead_id"])
    existing_run = _latest_agent_run_fields(lead["lead_id"]) if existing_lead else {}
    if existing_run:
        return {
            "status": "duplicate_ignored",
            "lead_id": lead["lead_id"],
            "reason": "Lead already has a saved agent run; skipped reprocessing and Telegram notification.",
            "airtable_record": existing_lead,
        }

    active_job = find_active_job_by_lead_id(lead["lead_id"])
    if active_job:
        return {
            "status": "duplicate_queued",
            "lead_id": lead["lead_id"],
            "reason": "Lead already has a pending or running queue job.",
            "job": active_job,
            "airtable_record": existing_lead,
        }

    airtable_response = (
        {"existing_record": existing_lead}
        if existing_lead
        else create_lead(_airtable_lead_fields(lead))
    )

    job = enqueue_lead_job(lead["lead_id"], lead)

    return {
        "status": "queued",
        "lead_id": lead["lead_id"],
        "airtable_record": airtable_response,
        "job": job,
    }


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
def telegram_webhook(
    payload: dict[str, Any],
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if (
        TELEGRAM_WEBHOOK_SECRET
        and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    callback = payload.get("callback_query")
    if not callback:
        return {"ok": True, "ignored": "not_callback_query"}

    callback_id = callback["id"]
    data = callback.get("data", "")
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
        decision_label = "already approved ✅" if current_status == "approved_sent" else "already rejected ❌"
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

    answer_callback_query(callback_id, f"{decision.title()} received. Processing...")
    if chat_id and message_id:
        remove_approval_buttons(chat_id=chat_id, message_id=message_id)

    result = resume_lead_send(lead_id, decision)

    approval_status = "approved_sent" if decision == "approve" else "rejected_by_owner"
    airtable_status_update = update_latest_agent_run_status(
        lead_id=lead_id,
        approval_status=approval_status,
    )
    queue_status_update = mark_latest_waiting_job_resolved(
        lead_id=lead_id,
        status=approval_status,
    )

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
        "telegram_edit": edit_result,
        "airtable_status_update": airtable_status_update,
        "queue_status_update": queue_status_update,
    }


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


def _airtable_lead_fields(lead: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in lead.items() if value != ""}


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
    from agents.common import structured_or_last_message
    from graph import graph

    prompt = (
        f"Run the lead intake workflow for {lead_id}. Qualify it, find missing info, "
        "draft the reply, save the CRM note, save artifacts, and apply the risk-based "
        "send policy from the saved decision. Request approval for risky responses, "
        "do not send when policy says do_not_send, and leave safe auto-send responses "
        "for the background worker after the graph completes."
    )
    config = {
        "configurable": {
            "thread_id": f"lead-{lead_id}",
        },
        "run_name": f"lead-intake-{lead_id}",
        "tags": ["webhook", "tally", "lead_intake"],
        "metadata": {
            "lead_id": lead_id,
            "thread_id": f"lead-{lead_id}",
            "source": "tally",
            "workflow": "lead_intake",
        },
    }
    result = graph.invoke(
        {"messages": [{"role": "user", "content": prompt}]},
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
        "summary": structured_or_last_message(result),
        "interrupt": None,
    }


def resume_lead_send(lead_id: str, decision: str) -> dict[str, Any]:
    from agents.common import structured_or_last_message
    from graph import graph

    config = {
        "configurable": {
            "thread_id": f"lead-{lead_id}",
        },
        "run_name": f"{decision}-send-{lead_id}",
        "tags": ["approval", "lead_intake"],
        "metadata": {
            "lead_id": lead_id,
            "thread_id": f"lead-{lead_id}",
            "decision": decision,
            "workflow": "lead_intake",
        },
    }

    result = graph.invoke(Command(resume=decision), config=config)

    return {
        "status": decision,
        "lead_id": lead_id,
        "result": structured_or_last_message(result),
    }
