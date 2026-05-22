from __future__ import annotations

import json
from typing import Any
from urllib.request import Request

from config import (
    EMAIL_TRANSPORT,
    RESEND_API_KEY,
    RESEND_FROM_EMAIL,
    RESEND_REPLY_TO_EMAIL,
)
from tools.http_client import request_json_with_retries
from tools.io_helpers import new_run_id, now_iso, output_run_dir, write_json

RESEND_SEND_URL = "https://api.resend.com/emails"


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
    provider_response: dict[str, Any] | None = None,
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
    if provider_response is not None:
        payload["provider_response"] = provider_response
    return {"sent_email_path": write_json(path, payload)}


def send_customer_email(
    *,
    lead_id: str,
    to: str,
    subject: str,
    body: str,
    approval_required: bool = True,
    send_policy: str = "approval_required",
    send_policy_reason: str = "",
) -> dict:
    if EMAIL_TRANSPORT == "simulated":
        return write_sent_email_artifact(
            lead_id=lead_id,
            to=to,
            subject=subject,
            body=body,
            transport=_simulated_transport_label(send_policy, approval_required),
            approval_required=approval_required,
            send_policy=send_policy,
            send_policy_reason=send_policy_reason,
        )

    if EMAIL_TRANSPORT == "resend":
        provider_response = _send_resend_email(to=to, subject=subject, body=body)
        return write_sent_email_artifact(
            lead_id=lead_id,
            to=to,
            subject=subject,
            body=body,
            transport="resend",
            approval_required=approval_required,
            send_policy=send_policy,
            send_policy_reason=send_policy_reason,
            provider_response=provider_response,
        )

    raise ValueError(
        "Unsupported EMAIL_TRANSPORT. Use EMAIL_TRANSPORT=simulated or "
        "EMAIL_TRANSPORT=resend."
    )


def _simulated_transport_label(send_policy: str, approval_required: bool) -> str:
    if send_policy == "auto_send" and not approval_required:
        return "simulated_safe_auto_send"
    return "simulated_approved_send"


def _send_resend_email(*, to: str, subject: str, body: str) -> dict[str, Any]:
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
        raise ValueError("EMAIL_TRANSPORT=resend requires: " + ", ".join(missing))

    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "text": body,
        "reply_to": RESEND_REPLY_TO_EMAIL,
    }
    request = Request(
        RESEND_SEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return request_json_with_retries(request)
