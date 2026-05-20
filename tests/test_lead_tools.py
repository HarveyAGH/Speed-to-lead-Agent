from __future__ import annotations

import json

from schemas.lead import LeadSubmission
from tools.lead_storage import get_agency_profile, load_lead, load_mock_lead


def _tool_result(tool, *args, **kwargs):
    # LangChain StructuredTool exposes invoke; fallback keeps tests readable if
    # the decorator implementation changes.
    if hasattr(tool, "invoke"):
        return tool.invoke(*args, **kwargs)
    return tool(*args, **kwargs)


def test_mock_lead_matches_submission_schema():
    payload = _tool_result(load_mock_lead, {"lead_id": "lead_001"})
    lead = LeadSubmission.model_validate_json(payload)
    assert lead.lead_id == "lead_001"
    assert lead.email == "maya@clearviewdental.example"


def test_load_lead_falls_back_to_mock_data_without_airtable(monkeypatch):
    monkeypatch.setattr("tools.lead_storage.airtable_is_configured", lambda: False)
    payload = _tool_result(load_lead, {"lead_id": "lead_001"})
    lead = json.loads(payload)
    assert lead["lead_id"] == "lead_001"
    assert lead["_source"] == "mock_data"


def test_agency_profile_has_required_rules():
    payload = _tool_result(get_agency_profile, {})
    profile = json.loads(payload)
    assert "required_fields_for_sales_call" in profile
    assert "monthly_ad_budget_minimum_usd" in profile["ideal_customer_profile"]
