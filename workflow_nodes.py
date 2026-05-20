from __future__ import annotations

import json
from typing import Any, Literal

from langgraph.types import interrupt

from config import MODEL
from agents.crm_recorder import build_crm_recorder
from agents.followup_writer import build_followup_writer
from agents.lead_qualifier import build_lead_qualifier
from agents.missing_info_detector import build_missing_info_detector

lead_qualifier_agent = build_lead_qualifier(MODEL)
missing_info_detector_agent = build_missing_info_detector(MODEL)
followup_writer_agent = build_followup_writer(MODEL)
crm_recorder_agent = build_crm_recorder(MODEL)

from state import LeadWorkflowState
from agents.common import structured_or_last_message
from tools.crm import save_run_artifacts
from tools.decision_normalizer import normalize_decision
from tools.email import write_sent_email_artifact
from tools.lead_storage import load_lead


def load_lead_node(state: LeadWorkflowState) -> dict[str, Any]:
    lead_id = state["lead_id"]

    raw = load_lead.invoke({"lead_id": lead_id})
    lead = json.loads(raw)

    return {
        "lead": lead,
    }


def qualify_node(state: LeadWorkflowState) -> dict[str, Any]:
    lead = state["lead"]

    result = lead_qualifier_agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(lead, ensure_ascii=False),
                }
            ]
        }
    )

    qualification = _extract_structured_dict(result)

    return {
        "qualification": qualification,
    }


def detect_missing_node(state: LeadWorkflowState) -> dict[str, Any]:
    lead = state["lead"]

    result = missing_info_detector_agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(lead, ensure_ascii=False),
                }
            ]
        }
    )

    missing_info = _extract_structured_dict(result)

    return {
        "missing_info": missing_info,
    }


def draft_followup_node(state: LeadWorkflowState) -> dict[str, Any]:
    context = {
        "lead": state["lead"],
        "qualification": state["qualification"],
        "missing_info": state["missing_info"],
    }

    result = followup_writer_agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                }
            ]
        }
    )

    draft = _extract_structured_dict(result)

    return {
        "draft": draft,
    }


def save_crm_note_node(state: LeadWorkflowState) -> dict[str, Any]:
    context = {
        "lead": state["lead"],
        "qualification": state["qualification"],
        "missing_info": state["missing_info"],
        "draft": state["draft"],
    }

    result = crm_recorder_agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                }
            ]
        }
    )

    crm_note = _extract_structured_dict(result)

    return {
        "crm_note": crm_note,
    }


def save_artifacts_node(state: LeadWorkflowState) -> dict[str, Any]:
    lead = state["lead"]
    qualification = state["qualification"]
    missing_info = state["missing_info"]
    draft = state["draft"]

    raw_decision = {
        "lead_id": state["lead_id"],
        "classification": qualification.get("lead_type"),
        "fit": qualification.get("fit"),
        "urgency": qualification.get("urgency"),
        "score": qualification.get("score"),
        "recommended_next_action": qualification.get("recommended_next_action"),
    }

    decision = normalize_decision(raw_decision, fallback_lead_id=state["lead_id"])

    evidence = {
        "qualification_evidence": qualification.get("evidence", []),
        "missing_required_fields": missing_info.get("missing_required_fields", []),
        "missing_helpful_fields": missing_info.get("missing_helpful_fields", []),
        "can_respond_now": missing_info.get("can_respond_now"),
    }

    raw_artifacts = save_run_artifacts.invoke(
        {
            "lead_id": state["lead_id"],
            "decision_json": json.dumps(decision),
            "draft_subject": draft.get("subject", ""),
            "draft_body": draft.get("body", ""),
            "evidence_json": json.dumps(evidence),
        }
    )

    artifacts = json.loads(raw_artifacts)

    return {
        "decision": decision,
        "evidence": evidence,
        "artifact_paths": artifacts.get("paths", {}),
        "artifact_run_id": artifacts.get("run_id", ""),
        "send_policy": decision["send_policy"],
    }


def approval_gate_node(state: LeadWorkflowState) -> dict[str, Any]:
    draft = state["draft"]
    decision = state["decision"]
    lead = state["lead"]

    approval_decision = interrupt(
        {
            "action": "send_followup_email",
            "description": "Human approval required before customer-facing email send.",
            "allowed_decisions": ["approve", "reject"],
            "resume_hint": "Tap approve to send, or reject to cancel.",
            "lead_id": state["lead_id"],
            "to": lead.get("email", ""),
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "send_policy_reason": decision.get("send_policy_reason", ""),
        }
    )

    normalized = _normalize_approval_decision(approval_decision)

    return {
        "approval_decision": normalized,
    }


def send_node(state: LeadWorkflowState) -> dict[str, Any]:
    lead = state["lead"]
    draft = state["draft"]
    decision = state["decision"]
    policy = state.get("send_policy") or decision.get("send_policy") or "approval_required"

    sent_email = write_sent_email_artifact(
        lead_id=state["lead_id"],
        to=lead.get("email", ""),
        subject=draft.get("subject", ""),
        body=draft.get("body", ""),
        transport=(
            "simulated_safe_auto_send"
            if policy == "auto_send"
            else "simulated_approved_send"
        ),
        approval_required=policy != "auto_send",
        send_policy=policy,
        send_policy_reason=decision.get("send_policy_reason", ""),
    )

    return {
        "sent_email": sent_email,
        "final_status": "sent",
    }


def do_not_send_node(state: LeadWorkflowState) -> dict[str, Any]:
    return {
        "final_status": "not_sent",
    }


def final_summary_node(state: LeadWorkflowState) -> dict[str, Any]:
    decision = state.get("decision", {})
    draft = state.get("draft", {})
    crm_note = state.get("crm_note", {})

    summary = "\n".join(
        [
            f"Lead workflow complete for {state['lead_id']}.",
            "",
            f"Classification: {decision.get('classification')}",
            f"Fit: {decision.get('fit')}",
            f"Urgency: {decision.get('urgency')}",
            f"Score: {decision.get('score')}",
            f"Recommended action: {decision.get('recommended_next_action')}",
            f"Send policy: {decision.get('send_policy')}",
            f"Final status: {state.get('final_status', 'pending')}",
            "",
            f"Draft subject: {draft.get('subject', '')}",
            f"CRM note: {crm_note.get('note_path', '')}",
            f"Artifacts: {json.dumps(state.get('artifact_paths', {}), indent=2)}",
        ]
    )

    return {
        "summary": summary,
    }


def route_after_save(
    state: LeadWorkflowState,
) -> Literal["approval_gate", "send", "do_not_send"]:
    policy = state.get("send_policy") or "do_not_send"

    if policy == "approval_required":
        return "approval_gate"

    if policy == "auto_send":
        return "send"

    return "do_not_send"


def route_after_approval(
    state: LeadWorkflowState,
) -> Literal["send", "do_not_send"]:
    decision = state.get("approval_decision")

    if decision == "approve":
        return "send"

    return "do_not_send"


def _extract_structured_dict(result: Any) -> dict[str, Any]:
    structured = result.get("structured_response") if isinstance(result, dict) else None

    if structured is not None:
        if hasattr(structured, "model_dump"):
            return structured.model_dump()
        if isinstance(structured, dict):
            return structured

    content = structured_or_last_message(result)

    try:
        value = json.loads(content)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    return {
        "raw_output": content,
    }


def _normalize_approval_decision(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip().lower()
        return "approve" if text == "approve" else "reject"

    if isinstance(value, dict):
        if "decision" in value:
            return _normalize_approval_decision(value["decision"])
        if "type" in value:
            return _normalize_approval_decision(value["type"])

    return "reject"
