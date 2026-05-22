from __future__ import annotations

from tools.io_helpers import new_run_id, now_iso, output_run_dir, write_json


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
