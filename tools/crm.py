from __future__ import annotations

import json

from tools.airtable_client import airtable_is_configured, create_agent_run
from tools.io_helpers import new_run_id, now_iso, output_run_dir, write_json, write_text
from tools.decision_normalizer import normalize_decision


def save_run_artifacts(
    lead_id: str,
    decision_json: str,
    draft_subject: str,
    draft_body: str,
    evidence_json: str,
    crm_note_json: str = "",
) -> str:
    run_id = new_run_id(f"lead_{lead_id}")
    run_dir = output_run_dir(run_id)
    raw_decision = _loads_or_error(decision_json, "invalid_decision_json")
    if "error" in raw_decision:
        return json.dumps(raw_decision, indent=2)

    evidence = _loads_or_error(evidence_json, "invalid_evidence_json")
    if "error" in evidence:
        return json.dumps(evidence, indent=2)

    crm_note = {}
    if crm_note_json:
        crm_note = _loads_or_error(crm_note_json, "invalid_crm_note_json")
        if "error" in crm_note:
            return json.dumps(crm_note, indent=2)

    decision = normalize_decision(raw_decision, fallback_lead_id=lead_id)
    paths = {
        "decision": write_json(
            run_dir / "decision.json",
            decision,
        ),
        "draft": write_text(
            run_dir / "draft_message.txt",
            f"Subject: {draft_subject}\n\n{draft_body}\n",
        ),
        "evidence": write_json(run_dir / "evidence.json", evidence),
    }
    if crm_note:
        paths["crm_note"] = write_text(
            run_dir / "crm_note.md",
            _build_crm_note_markdown(
                lead_id=lead_id,
                crm_note=crm_note,
                evidence=evidence,
                decision=decision,
            ),
        )

    airtable_result = None
    if airtable_is_configured():
        try:
            fields = {
                "run_id": run_id,
                "lead_id": lead_id,
                "classification": decision["classification"],
                "fit": decision["fit"],
                "urgency": decision["urgency"],
                "score": decision["score"],
                "recommended_next_action": decision["recommended_next_action"],
                "draft_subject": draft_subject,
                "draft_body": draft_body,
                "evidence_json": evidence_json,
                "approval_status": "drafted_only",
                "artifact_paths": json.dumps(paths, indent=2),
                "created_at": now_iso(),
            }
            airtable_result = create_agent_run(fields)
        except Exception as exc:
            airtable_result = {"error": str(exc)}

    return json.dumps(
        {
            "run_id": run_id,
            "paths": paths,
            "decision": decision,
            "airtable": airtable_result or {"configured": False},
        },
        indent=2,
    )


def _build_crm_note_markdown(
    *,
    lead_id: str,
    crm_note: dict,
    evidence: dict,
    decision: dict,
) -> str:
    summary = str(crm_note.get("summary") or "").strip()
    saved_fields = crm_note.get("saved_fields") or []

    return "\n".join(
        [
            f"# CRM Note: {lead_id}",
            "",
            f"- Saved at: {now_iso()}",
            f"- CRM status: {crm_note.get('crm_status', '')}",
            f"- Classification: {decision.get('classification', '')}",
            f"- Fit: {decision.get('fit', '')}",
            f"- Urgency: {decision.get('urgency', '')}",
            f"- Score: {decision.get('score', '')}",
            f"- Recommended action: {decision.get('recommended_next_action', '')}",
            f"- Send policy: {decision.get('send_policy', '')}",
            "",
            "## Owner Summary",
            summary,
            "",
            "## Saved Fields",
            json.dumps(saved_fields, indent=2),
            "",
            "## Evidence",
            json.dumps(evidence, indent=2),
            "",
        ]
    )


def _loads_or_error(raw_json: str, error: str) -> dict:
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return {
            "error": error,
            "detail": str(exc),
        }

    if not isinstance(value, dict):
        return {
            "error": error,
            "detail": "Expected a JSON object.",
        }
    return value
