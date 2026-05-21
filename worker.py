from __future__ import annotations

import argparse
import json
import logging
import time
import traceback
from functools import lru_cache
from typing import Any

from langgraph.errors import GraphInterrupt

from channels.channel_dispatcher import dispatch_lead_response
from agents.speed_to_lead_chat import build_speed_to_lead_chat
from app import (
    _latest_agent_run_fields,
    _owner_summary_from_run,
    run_approval_workflow_status,
)
from config import MODEL
from tools.channel_conversations import (
    append_channel_message,
    get_conversation_context,
    setup_channel_conversations,
    update_conversation_state,
)
from tools.channel_crm import write_channel_lead_snapshot
from tools.job_queue import (
    claim_next_lead_job,
    list_recent_jobs,
    mark_lead_job_completed,
    mark_lead_job_failed,
    mark_lead_job_succeeded,
    mark_lead_job_waiting_approval,
    recover_stale_running_jobs,
    setup_job_queue,
)
from tools.airtable_client import update_latest_agent_run_status
from tools.lead_storage import get_agency_profile
from tools.owner_config import get_owner_config
from tools.telegram import (
    send_owner_approval_request,
    send_owner_channel_escalation,
    send_owner_status_notification,
)


logger = logging.getLogger("lead_worker")


@lru_cache(maxsize=1)
def _channel_chat_agent():
    return build_speed_to_lead_chat(MODEL)


def process_one_job() -> dict[str, Any] | None:
    job = claim_next_lead_job()
    if not job:
        return None

    job_id = job["id"]
    lead_id = job["lead_id"]
    job_type = str(job.get("job_type") or "form_intake")
    payload = dict(job.get("payload") or {})
    source_channel = str(payload.get("source_channel") or "")
    channel_user_id = str(payload.get("channel_user_id") or "")

    if job_type == "channel_message":
        return process_channel_message_job(job)

    try:
        telegram_result = None
        channel_dispatch_result = None
        workflow_state: dict[str, Any] = {}
        try:
            workflow_result = run_approval_workflow_status(lead_id)
            workflow_status = workflow_result["status"]
            workflow_summary = workflow_result["summary"]
            workflow_state = dict(workflow_result.get("state") or {})
        except GraphInterrupt as exc:
            workflow_status = "pending_approval"
            workflow_summary = (
                "The workflow paused at a human approval boundary. "
                f"Interrupt detail: {exc}"
            )

        latest_run = _latest_agent_run_fields(lead_id)
        decision = workflow_state.get("decision") or _decision_from_latest_run(latest_run)
        send_policy = str(
            workflow_state.get("send_policy")
            or decision.get("send_policy")
            or "approval_required"
        )

        if workflow_status == "pending_approval":
            telegram_result = send_owner_approval_request(
                lead_id=lead_id,
                lead_name=str(payload.get("name") or ""),
                company=str(payload.get("company") or ""),
                recommendation=latest_run.get("recommended_next_action")
                or "Review drafted follow-up",
                summary=_owner_summary_from_run(latest_run),
                classification=latest_run.get("classification", ""),
                fit=latest_run.get("fit", ""),
                urgency=latest_run.get("urgency", ""),
                score=latest_run.get("score", ""),
                draft_subject=latest_run.get("draft_subject", ""),
                draft_body=latest_run.get("draft_body", ""),
            )
            if not _notification_delivered(telegram_result):
                raise RuntimeError(
                    "Approval required, but owner Telegram notification failed: "
                    f"{telegram_result}"
                )
            mark_lead_job_waiting_approval(job_id)
        else:
            completion_status = _completion_status_from_state(
                workflow_state=workflow_state,
                send_policy=send_policy,
            )

            if completion_status == "auto_sent":
                channel_dispatch_result = _dispatch_auto_send_response(
                    source_channel=source_channel,
                    channel_user_id=channel_user_id,
                    latest_run=latest_run,
                )
                if (
                    source_channel
                    and channel_dispatch_result
                    and channel_dispatch_result.get("ok") is False
                ):
                    raise RuntimeError(
                        "Auto-send policy selected a channel response, but "
                        f"dispatch failed: {channel_dispatch_result}"
                    )

            if completion_status != "succeeded":
                update_latest_agent_run_status(
                    lead_id=lead_id,
                    approval_status=completion_status,
                )
                mark_lead_job_completed(
                    job_id,
                    completion_status,
                    first_response=completion_status == "auto_sent",
                )
            else:
                mark_lead_job_succeeded(job_id)

            telegram_result = send_owner_status_notification(
                lead_id=lead_id,
                lead_name=str(payload.get("name") or ""),
                company=str(payload.get("company") or ""),
                status=_owner_status_label(completion_status),
                summary=_owner_summary_from_policy(latest_run, decision, completion_status),
                classification=latest_run.get("classification", ""),
                fit=latest_run.get("fit", ""),
                urgency=latest_run.get("urgency", ""),
                score=latest_run.get("score", ""),
                draft_subject=latest_run.get("draft_subject", ""),
                draft_body=latest_run.get("draft_body", ""),
            )

        return {
            "job_id": job_id,
            "lead_id": lead_id,
            "job_type": job_type,
            "status": workflow_status,
            "summary": workflow_summary,
            "send_policy": send_policy,
            "source_channel": source_channel or None,
            "sent_email": workflow_state.get("sent_email"),
            "channel_dispatch": channel_dispatch_result,
            "telegram": telegram_result,
        }
    except Exception as exc:
        logger.error(
            "job_failed lead_id=%s job_id=%s error=%s",
            lead_id,
            job_id,
            str(exc),
            exc_info=True,
        )
        failure = mark_lead_job_failed(job_id, traceback.format_exc())
        return {
            "job_id": job_id,
            "lead_id": lead_id,
            "job_type": job_type,
            "status": "failed_or_requeued",
            "error": str(exc),
            "queue": failure,
        }


def process_channel_message_job(job: dict[str, Any]) -> dict[str, Any]:
    job_id = job["id"]
    lead_id = job["lead_id"]
    payload = dict(job.get("payload") or {})
    source_channel = str(payload.get("source_channel") or "")
    channel_user_id = str(payload.get("channel_user_id") or "")
    sender_name = str(payload.get("sender_name") or "")

    try:
        context = get_conversation_context(
            source_channel=source_channel,
            channel_user_id=channel_user_id,
        )
        if not context:
            raise RuntimeError(
                f"No channel conversation found for {source_channel}:{channel_user_id}"
            )
        owner_already_escalated = bool(context.get("last_owner_escalated_at"))
        customer_text = str(payload.get("text") or "")

        if _conversation_is_handoff_pending(str(context.get("status") or "")):
            reply_text = _handoff_pending_reply()
            append_channel_message(
                conversation_id=int(context["id"]),
                role="assistant",
                content=reply_text,
            )
            dispatch_result = dispatch_lead_response(
                source_channel=source_channel,
                channel_user_id=channel_user_id,
                subject="",
                body=reply_text,
            )
            if dispatch_result.get("ok") is False:
                raise RuntimeError(f"Channel holding reply dispatch failed: {dispatch_result}")

            mark_lead_job_completed(
                job_id,
                "handoff_pending_replied",
                first_response=True,
            )
            return {
                "job_id": job_id,
                "lead_id": lead_id,
                "job_type": "channel_message",
                "status": "handoff_pending_replied",
                "conversation_status": context.get("status"),
                "source_channel": source_channel,
                "channel_dispatch": dispatch_result,
                "owner_notification": None,
                "decision": {
                    "reason": (
                        "Lead is already in owner handoff state; "
                        "no LLM call made."
                    ),
                },
            }

        if _conversation_is_terminal(str(context.get("status") or "")):
            mark_lead_job_completed(
                job_id,
                "conversation_already_closed",
                first_response=False,
            )
            return {
                "job_id": job_id,
                "lead_id": lead_id,
                "job_type": "channel_message",
                "status": "conversation_already_closed",
                "conversation_status": context.get("status"),
                "source_channel": source_channel,
                "channel_dispatch": None,
                "owner_notification": None,
                "decision": {
                    "reason": "Conversation is already terminal; no LLM call made.",
                },
            }

        if _customer_is_closing_conversation(customer_text):
            final_reply = _closing_reply(owner_already_escalated=owner_already_escalated)
            append_channel_message(
                conversation_id=int(context["id"]),
                role="assistant",
                content=final_reply,
            )
            dispatch_result = dispatch_lead_response(
                source_channel=source_channel,
                channel_user_id=channel_user_id,
                subject="",
                body=final_reply,
            )
            if dispatch_result.get("ok") is False:
                raise RuntimeError(f"Channel closing reply dispatch failed: {dispatch_result}")

            updated_conversation = update_conversation_state(
                conversation_id=int(context["id"]),
                extracted_profile=dict(context.get("extracted_profile") or {}),
                status="customer_closed",
                owner_escalated=False,
            )
            mark_lead_job_completed(
                job_id,
                "customer_closed",
                first_response=True,
            )
            return {
                "job_id": job_id,
                "lead_id": lead_id,
                "job_type": "channel_message",
                "status": "customer_closed",
                "conversation_status": updated_conversation.get("status"),
                "source_channel": source_channel,
                "channel_dispatch": dispatch_result,
                "owner_notification": None,
                "decision": {
                    "reason": "Customer sent a clear closing message; no LLM call made.",
                    "owner_already_escalated": owner_already_escalated,
                },
            }

        agent_context = {
            "lead_id": lead_id,
            "source_channel": source_channel,
            "channel_user_id": channel_user_id,
            "sender_name": sender_name,
            "conversation_status": context.get("status"),
            "owner_already_escalated": owner_already_escalated,
            "last_owner_escalated_at": str(context.get("last_owner_escalated_at") or ""),
            "existing_extracted_profile": context.get("extracted_profile") or {},
            "recent_messages": _message_context(context.get("messages", [])),
            "agency_profile": json.loads(get_agency_profile.invoke({})),
            "owner_config": get_owner_config(),
        }
        decision_model = _channel_chat_agent().invoke(
            {"input": json.dumps(agent_context, ensure_ascii=False)}
        )
        decision = decision_model.model_dump()
        raw_conversation_status = str(
            decision.get("conversation_status") or "continue_conversation"
        )
        stored_conversation_status = _stored_conversation_status(decision)
        reply_text = _reply_text_for_decision(decision)

        append_channel_message(
            conversation_id=int(context["id"]),
            role="assistant",
            content=reply_text,
        )

        dispatch_result = dispatch_lead_response(
            source_channel=source_channel,
            channel_user_id=channel_user_id,
            subject="",
            body=reply_text,
        )
        if dispatch_result.get("ok") is False:
            raise RuntimeError(f"Channel reply dispatch failed: {dispatch_result}")

        owner_escalation_required = bool(decision.get("owner_escalation_required"))
        should_notify_owner = _should_notify_owner(
            owner_escalation_required=owner_escalation_required,
            owner_already_escalated=owner_already_escalated,
        )
        updated_conversation = update_conversation_state(
            conversation_id=int(context["id"]),
            extracted_profile=dict(decision.get("extracted_profile") or {}),
            status=stored_conversation_status,
            owner_escalated=should_notify_owner,
        )

        crm_writeback = write_channel_lead_snapshot(
            lead_id=lead_id,
            source_channel=source_channel,
            channel_user_id=channel_user_id,
            sender_name=sender_name,
            extracted_profile=dict(decision.get("extracted_profile") or {}),
            latest_customer_message=customer_text,
            owner_summary=str(decision.get("owner_summary") or ""),
            qualification_summary=str(decision.get("qualification_summary") or ""),
            status=_airtable_status_for_channel(
                raw_conversation_status=raw_conversation_status,
                stored_conversation_status=stored_conversation_status,
            ),
        )

        owner_notification = None
        if should_notify_owner:
            owner_notification = send_owner_channel_escalation(
                lead_id=lead_id,
                source_channel=source_channel,
                sender_name=sender_name,
                channel_user_id=channel_user_id,
                owner_summary=str(decision.get("owner_summary") or ""),
                qualification_summary=str(decision.get("qualification_summary") or ""),
                fit=str(decision.get("fit") or ""),
                urgency=str(decision.get("urgency") or ""),
                score=decision.get("score", ""),
                extracted_profile=dict(decision.get("extracted_profile") or {}),
                transcript=_message_context(context.get("messages", []))
                + [{"role": "assistant", "content": reply_text}],
            )
            if not _notification_delivered(owner_notification):
                raise RuntimeError(
                    "Owner escalation required, but Telegram notification failed: "
                    f"{owner_notification}"
                )

        completion_status = _channel_completion_status(
            decision,
            owner_escalation_required=owner_escalation_required,
            owner_already_escalated=owner_already_escalated,
            owner_notification_sent=should_notify_owner,
        )
        mark_lead_job_completed(
            job_id,
            completion_status,
            first_response=True,
        )

        return {
            "job_id": job_id,
            "lead_id": lead_id,
            "job_type": "channel_message",
            "status": completion_status,
            "conversation_status": updated_conversation.get("status"),
            "source_channel": source_channel,
            "channel_dispatch": dispatch_result,
            "crm_writeback": crm_writeback,
            "owner_notification": owner_notification,
            "decision": {
                "conversation_status": decision.get("conversation_status"),
                "stored_conversation_status": stored_conversation_status,
                "fit": decision.get("fit"),
                "urgency": decision.get("urgency"),
                "score": decision.get("score"),
                "owner_escalation_required": owner_escalation_required,
                "owner_already_escalated": owner_already_escalated,
                "owner_notification_sent": should_notify_owner,
            },
        }
    except Exception as exc:
        logger.error(
            "channel_job_failed lead_id=%s job_id=%s error=%s",
            lead_id,
            job_id,
            str(exc),
            exc_info=True,
        )
        failure = mark_lead_job_failed(job_id, traceback.format_exc())
        return {
            "job_id": job_id,
            "lead_id": lead_id,
            "job_type": "channel_message",
            "status": "failed_or_requeued",
            "error": str(exc),
            "queue": failure,
        }


def run_worker(poll_interval: float) -> None:
    setup_job_queue()
    setup_channel_conversations()
    recover_stale_running_jobs()
    logger.info("Lead worker started. Waiting for queued jobs.")
    while True:
        result = process_one_job()
        if result:
            logger.info("job_result=%s", json.dumps(_loggable_job_result(result), default=str))
            continue
        time.sleep(poll_interval)


def _completion_status_from_state(
    *,
    workflow_state: dict[str, Any],
    send_policy: str,
) -> str:
    final_status = str(workflow_state.get("final_status") or "")
    if final_status == "sent" and send_policy == "auto_send":
        return "auto_sent"
    if final_status == "sent":
        return "approved_sent"
    if final_status == "not_sent":
        return "not_sent"
    return "succeeded"


def _loggable_job_result(result: dict[str, Any]) -> dict[str, Any]:
    telegram = result.get("telegram") or result.get("owner_notification") or {}
    channel_dispatch = result.get("channel_dispatch") or {}
    crm_writeback = result.get("crm_writeback") or {}
    queue = result.get("queue") or {}

    return {
        "job_id": result.get("job_id"),
        "lead_id": result.get("lead_id"),
        "job_type": result.get("job_type"),
        "status": result.get("status"),
        "conversation_status": result.get("conversation_status"),
        "send_policy": result.get("send_policy"),
        "source_channel": result.get("source_channel"),
        "channel_dispatch_ok": _nested_ok(channel_dispatch),
        "owner_notification_ok": _nested_ok(telegram),
        "crm_action": crm_writeback.get("action"),
        "queue_status": queue.get("status"),
        "error": result.get("error"),
    }


def _nested_ok(value: Any) -> bool | None:
    if not isinstance(value, dict) or not value:
        return None
    if "ok" in value:
        return bool(value.get("ok"))
    nested = value.get("result")
    if isinstance(nested, dict) and "ok" in nested:
        return bool(nested.get("ok"))
    return None


def _should_notify_owner(
    *,
    owner_escalation_required: bool,
    owner_already_escalated: bool,
) -> bool:
    return owner_escalation_required and not owner_already_escalated


def _channel_completion_status(
    decision: dict[str, Any],
    *,
    owner_escalation_required: bool | None = None,
    owner_already_escalated: bool = False,
    owner_notification_sent: bool = False,
) -> str:
    status = str(decision.get("conversation_status") or "")
    if status == "qualified_escalate":
        if owner_already_escalated and not owner_notification_sent:
            return "already_escalated_replied"
        return "owner_escalated"
    if status == "qualified_handoff_pending_owner":
        return "handoff_pending_replied"
    if owner_escalation_required and owner_already_escalated and not owner_notification_sent:
        return "already_escalated_replied"
    if status == "not_fit_close":
        return "conversation_closed"
    if status == "customer_closed":
        return "customer_closed"
    if status == "needs_human":
        return "needs_human"
    return "conversation_replied"


def _airtable_status_for_channel(
    *,
    raw_conversation_status: str,
    stored_conversation_status: str,
) -> str:
    if raw_conversation_status == "qualified_escalate":
        return "qualified_messaging_lead"
    if stored_conversation_status == "not_fit_close":
        return "messaging_not_fit"
    if stored_conversation_status == "customer_closed":
        return "messaging_customer_closed"
    if stored_conversation_status == "needs_human":
        return "messaging_needs_human"
    if stored_conversation_status == "qualified_handoff_pending_owner":
        return "qualified_messaging_lead"
    return "messaging_active"


def _conversation_is_terminal(status: str) -> bool:
    return status in {
        "customer_closed",
        "not_fit_close",
        "owner_taking_over",
        "owner_marked_booked",
        "owner_marked_not_fit",
    }


def _conversation_is_handoff_pending(status: str) -> bool:
    return status == "qualified_handoff_pending_owner"


def _stored_conversation_status(decision: dict[str, Any]) -> str:
    status = str(decision.get("conversation_status") or "continue_conversation")
    if status == "qualified_escalate":
        return "qualified_handoff_pending_owner"
    if status == "not_fit_close" and _looks_like_nurture_not_ready(decision):
        return "continue_conversation"
    return status


def _looks_like_nurture_not_ready(decision: dict[str, Any]) -> bool:
    profile = {
        str(key).lower(): str(value or "").lower()
        for key, value in dict(decision.get("extracted_profile") or {}).items()
    }
    combined = " ".join(
        [
            str(decision.get("reply_text") or "").lower(),
            str(decision.get("owner_summary") or "").lower(),
            str(decision.get("qualification_summary") or "").lower(),
            " ".join(profile.values()),
        ]
    )

    if any(
        marker in combined
        for marker in (
            "vendor",
            "spam",
            "backlink",
            "guest post",
            "seo backlinks",
            "selling links",
            "job applicant",
        )
    ):
        return False

    has_real_business = any(
        key in profile and profile[key] not in {"", "unknown", "<unknown>", "n/a"}
        for key in ("business_type", "monthly_revenue", "monthly_inquiry_volume")
    )
    too_early_signals = any(
        marker in combined
        for marker in (
            "too early",
            "overkill",
            "doesn't make financial sense",
            "does not make financial sense",
            "not viable",
            "low revenue",
            "no website",
            "$450",
            "6 inquiries",
        )
    )
    service_interest = profile.get("service_interest", "")
    wants_automation = any(
        marker in combined
        for marker in ("ai automation", "automation", "respond", "customer messages")
    ) or bool(service_interest)

    return has_real_business and too_early_signals and wants_automation


def _reply_text_for_decision(decision: dict[str, Any]) -> str:
    reply = str(decision.get("reply_text") or "").strip()
    if str(decision.get("conversation_status") or "") != "qualified_escalate":
        return reply

    booking_url = _discovery_call_url()
    if not booking_url or booking_url in reply:
        return reply

    return (
        f"{reply}\n\n"
        f"If you want to grab a time directly, you can book here: {booking_url}"
    ).strip()


def _handoff_pending_reply() -> str:
    owner = get_owner_config()
    owner_name = str(owner.get("owner_name") or "the owner")
    booking_url = _discovery_call_url()

    if booking_url:
        return (
            f"{owner_name} has your details and will follow up as soon as possible. "
            f"If you want to book directly, use this link: {booking_url}"
        )

    return (
        f"{owner_name} has your details and will follow up as soon as possible. "
        "You are already in the handoff queue."
    )


def _discovery_call_url() -> str:
    owner = get_owner_config()
    return str(
        owner.get("discovery_call_url")
        or owner.get("calendar_url")
        or ""
    ).strip()


def _customer_is_closing_conversation(text: str) -> bool:
    normalized = "".join(
        char if char.isalnum() else " "
        for char in text.lower().strip()
    ).split()
    normalized = " ".join(normalized)
    if not normalized:
        return False

    closing_phrases = {
        "no",
        "no thanks",
        "no thank you",
        "nah",
        "not now",
        "that s all",
        "thats all",
        "all good",
        "i'm good",
        "im good",
        "nothing else",
        "no other questions",
        "nope",
        "thanks bye",
        "thank you bye",
    }
    if normalized in closing_phrases:
        return True

    return any(
        normalized.startswith(prefix)
        for prefix in (
            "no thanks ",
            "no thank you ",
            "nothing else ",
            "that s all ",
            "thats all ",
            "all good ",
        )
    )


def _closing_reply(*, owner_already_escalated: bool) -> str:
    owner = get_owner_config()
    business_name = str(owner.get("business_name") or "us")
    owner_name = str(owner.get("owner_name") or "the owner")

    if owner_already_escalated:
        return (
            f"Thanks for contacting {business_name}. "
            f"{owner_name} will reach out as soon as possible."
        )

    return (
        f"Thanks for contacting {business_name}. "
        "If anything changes, just send another message here."
    )


def _message_context(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "role": str(message.get("role") or ""),
            "content": str(message.get("content") or ""),
        }
        for message in messages
        if message.get("content")
    ]


def _dispatch_auto_send_response(
    *,
    source_channel: str,
    channel_user_id: str,
    latest_run: dict[str, Any],
) -> dict[str, Any] | None:
    if not source_channel or not channel_user_id:
        return None

    return dispatch_lead_response(
        source_channel=source_channel,
        channel_user_id=channel_user_id,
        subject=str(latest_run.get("draft_subject") or ""),
        body=str(latest_run.get("draft_body") or ""),
    )


def _decision_from_latest_run(run_fields: dict[str, Any]) -> dict[str, Any]:
    artifact_paths = run_fields.get("artifact_paths")
    if not artifact_paths:
        return {}

    try:
        paths = json.loads(str(artifact_paths))
        decision_path = paths["decision"]
        with open(decision_path, encoding="utf-8") as handle:
            return json.load(handle)
    except (KeyError, OSError, json.JSONDecodeError):
        return {}


def _owner_status_label(status: str) -> str:
    labels = {
        "auto_sent": "auto-sent safe first response",
        "not_sent": "not sent by policy",
        "succeeded": "workflow completed",
    }
    return labels.get(status, status)


def _owner_summary_from_policy(
    run_fields: dict[str, Any],
    decision: dict[str, Any],
    completion_status: str,
) -> str:
    policy = decision.get("send_policy") or "unknown"
    reason = decision.get("send_policy_reason") or "No policy reason was saved."
    base = _owner_summary_from_run(run_fields)

    if completion_status == "auto_sent":
        return (
            f"{base} The system auto-sent this because send_policy={policy}. "
            f"Reason: {reason}"
        )
    if completion_status == "not_sent":
        return (
            f"{base} The system did not send a customer-facing response because "
            f"send_policy={policy}. Reason: {reason}"
        )
    return base


def _notification_delivered(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    if result.get("configured") is False:
        return False
    return result.get("ok") is not False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Process queued lead intake jobs.")
    parser.add_argument("--once", action="store_true", help="Process one job and exit.")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--list", action="store_true", help="List recent queue jobs and exit.")
    args = parser.parse_args()

    setup_job_queue()
    setup_channel_conversations()

    if args.list:
        for job in list_recent_jobs():
            print(job)
        return 0

    if args.once:
        print(process_one_job() or {"status": "no_pending_jobs"})
        return 0

    run_worker(args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
