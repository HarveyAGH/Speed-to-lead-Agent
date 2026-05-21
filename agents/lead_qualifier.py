from __future__ import annotations

from typing import Any

from langchain.tools import tool

from agents.common import build_structured_chain, dump_structured_result, require_json_text
from schemas.lead import LeadQualificationReport


def build_lead_qualifier(model: Any):
    return build_structured_chain(model, "lead_qualifier.md", LeadQualificationReport)


def build_lead_qualifier_tool(model: Any):
    lead_qualifier = build_lead_qualifier(model)

    @tool(
        "lead_qualifier_agent",
        description=(
            "Classifies an inbound agency lead, scores fit and urgency, and "
            "returns a structured qualification report with evidence."
        ),
    )
    def call_lead_qualifier_agent(lead_submission_json: str = "") -> str:
        error = require_json_text(lead_submission_json, "lead_submission_json")
        if error:
            return error

        result = lead_qualifier.invoke({"input": lead_submission_json})
        return dump_structured_result(result)

    return call_lead_qualifier_agent
