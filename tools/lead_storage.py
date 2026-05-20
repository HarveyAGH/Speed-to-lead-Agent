from __future__ import annotations

import json
from pathlib import Path

from langchain.tools import tool

from config import MOCK_DATA_DIR
from tools.airtable_client import airtable_is_configured, find_lead_by_id


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@tool("load_mock_lead", description="Load a deterministic mock lead by lead_id from mock_data/leads.json.")
def load_mock_lead(lead_id: str) -> str:
    leads = _read_json(MOCK_DATA_DIR / "leads.json")
    for lead in leads:
        if lead["lead_id"] == lead_id:
            return json.dumps(lead, indent=2)
    return json.dumps(
        {
            "found": False,
            "lead_id": lead_id,
            "error": f"Unknown mock lead_id: {lead_id}",
        },
        indent=2,
    )


@tool(
    "load_lead",
    description=(
        "Load a lead by lead_id. Uses Airtable when configured; otherwise "
        "falls back to deterministic mock data."
    ),
)
def load_lead(lead_id: str) -> str:
    if airtable_is_configured():
        try:
            record = find_lead_by_id(lead_id)
        except Exception as exc:
            return json.dumps(
                {
                    "found": False,
                    "source": "airtable",
                    "lead_id": lead_id,
                    "error": str(exc),
                },
                indent=2,
            )

        if record is not None:
            lead = dict(record.get("fields", {}))
            lead.setdefault("lead_id", lead_id)
            lead["_airtable_record_id"] = record.get("id")
            lead["_source"] = "airtable"
            return json.dumps(lead, indent=2)

        return json.dumps(
            {
                "found": False,
                "source": "airtable",
                "lead_id": lead_id,
                "error": f"No Airtable lead found with lead_id: {lead_id}",
            },
            indent=2,
        )

    lead = json.loads(load_mock_lead.invoke({"lead_id": lead_id}))
    if isinstance(lead, dict):
        lead["_source"] = "mock_data"
    return json.dumps(lead, indent=2)


@tool("get_agency_profile", description="Return the demo agency profile and qualification rules.")
def get_agency_profile() -> str:
    return json.dumps(_read_json(MOCK_DATA_DIR / "agency_profile.json"), indent=2)
