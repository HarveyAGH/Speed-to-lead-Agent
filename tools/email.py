from __future__ import annotations

import json

from langchain.tools import tool
from langgraph.types import interrupt

from tools.io_helpers import new_run_id, now_iso, output_run_dir, write_json


def _normalize_human_decision(value) -> str:
    """Accept simple Studio resume values like approve, plus dict/list formats."""
    if isinstance(value, str):
        return value.strip().lower()

    if isinstance(value, dict):
        if "type" in value:
            return str(value["type"]).strip().lower()
        if "decision" in value:
            return str(value["decision"]).strip().lower()
        decisions = value.get("decisions")
        if isinstance(decisions, list) and decisions:
            return _normalize_human_decision(decisions[0])

    if isinstance(value, list) and value:
        return _normalize_human_decision(value[0])

    return "reject"


def write_sent_email_artifact(
    *,
    lead_id: str,
    to: str,
    subject: str,
    body: str,
    transport: str,
    approval_required: bool,
    send_policy: str,
    send_policy_reason: str = "",
) -> dict:
    run_id = new_run_id(f"email_{lead_id}")
    path = output_run_dir(run_id) / "sent_email.json"
    payload = {
        "lead_id": lead_id,
        "to": to,
        "subject": subject,
        "body": body,
        "sent_at": now_iso(),
        "transport": transport,
        "approval_required": approval_required,
        "send_policy": send_policy,
        "send_policy_reason": send_policy_reason,
    }
    return {"sent_email_path": write_json(path, payload)}


@tool(
    "send_followup_email",
    description=(
        "Send a customer-facing follow-up email after human approval. In this "
        "MVP, sending is simulated by writing a sent_email.json artifact."
    ),
)
def send_followup_email(lead_id: str, to: str, subject: str, body: str) -> str:
    decision = interrupt(
        {
            "action": "send_followup_email",
            "description": "Human approval required before customer-facing email send.",
            "allowed_decisions": ["approve", "reject"],
            "resume_hint": "Type approve to send, or reject to cancel.",
            "lead_id": lead_id,
            "to": to,
            "subject": subject,
            "body": body,
        }
    )

    if _normalize_human_decision(decision) != "approve":
        return json.dumps(
            {
                "sent": False,
                "lead_id": lead_id,
                "to": to,
                "reason": "Send cancelled by human reviewer.",
            },
            indent=2,
        )

    return json.dumps(
        write_sent_email_artifact(
            lead_id=lead_id,
            to=to,
            subject=subject,
            body=body,
            transport="simulated_approved_send",
            approval_required=True,
            send_policy="approval_required",
        ),
        indent=2,
    )


@tool(
    "send_safe_followup_email",
    description=(
        "Auto-send a low-risk first response without human approval. Use only "
        "when the saved decision send_policy is auto_send. In this MVP, sending "
        "is simulated by writing a sent_email.json artifact."
    ),
)
def send_safe_followup_email(
    lead_id: str,
    to: str,
    subject: str,
    body: str,
    send_policy_reason: str = "",
) -> str:
    return json.dumps(
        write_sent_email_artifact(
            lead_id=lead_id,
            to=to,
            subject=subject,
            body=body,
            transport="simulated_safe_auto_send",
            approval_required=False,
            send_policy="auto_send",
            send_policy_reason=send_policy_reason,
        ),
        indent=2,
    )
