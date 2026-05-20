from __future__ import annotations

import json

from langchain.tools import tool

from tools.airtable_client import airtable_is_configured, create_agent_run
from tools.io_helpers import new_run_id, now_iso, output_run_dir, write_json, write_text
from tools.decision_normalizer import normalize_decision



@tool("save_crm_note", description="Save a CRM-style note for a qualified inbound lead.")
def save_crm_note(
    lead_id: str,
    crm_status: str,
    owner_summary: str,
    next_action: str,
    evidence_json: str,
) -> str:
    run_id = new_run_id(f"lead_{lead_id}")
    note_path = output_run_dir(run_id) / "crm_note.md"
    evidence = _loads_or_error(evidence_json, "invalid_evidence_json")
    if "error" in evidence:
        return json.dumps(evidence, indent=2)

    note = "\n".join(
        [
            f"# CRM Note: {lead_id}",
            "",
            f"- Saved at: {now_iso()}",
            f"- Status: {crm_status}",
            f"- Next action: {next_action}",
            "",
            "## Owner Summary",
            owner_summary,
            "",
            "## Evidence",
            json.dumps(evidence, indent=2),
            "",
        ]
    )
    return write_text(note_path, note)


@tool(
    "save_run_artifacts",
    description=(
        "Save visible demo artifacts: decision.json, draft_message.txt, and evidence.json."
    ),
)
def save_run_artifacts(
    lead_id: str,
    decision_json: str,
    draft_subject: str,
    draft_body: str,
    evidence_json: str,
) -> str:
    run_id = new_run_id(f"lead_{lead_id}")
    run_dir = output_run_dir(run_id)
    raw_decision = _loads_or_error(decision_json, "invalid_decision_json")
    if "error" in raw_decision:
        return json.dumps(raw_decision, indent=2)

    evidence = _loads_or_error(evidence_json, "invalid_evidence_json")
    if "error" in evidence:
        return json.dumps(evidence, indent=2)

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
