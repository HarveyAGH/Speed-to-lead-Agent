from __future__ import annotations

from typing import Any, Literal, TypedDict


SendPolicy = Literal["auto_send", "approval_required", "do_not_send"]
ApprovalDecision = Literal["approve", "reject"]


class LeadWorkflowState(TypedDict, total=False):
    lead_id: str

    lead: dict[str, Any]

    qualification: dict[str, Any]
    missing_info: dict[str, Any]
    draft: dict[str, Any]
    crm_note: dict[str, Any]

    decision: dict[str, Any]
    evidence: dict[str, Any]
    artifact_paths: dict[str, str]
    artifact_run_id: str

    send_policy: SendPolicy
    approval_decision: ApprovalDecision

    sent_email: dict[str, Any]
    final_status: str
    summary: str
