from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.agents.structured_output import ToolStrategy

from agents.common import load_prompt, require_json_text, structured_or_last_message
from schemas.lead import LeadQualificationReport


def build_lead_qualifier(model: Any):
    return create_agent(
        model=model,
        tools=[],
        system_prompt=load_prompt("lead_qualifier.md"),
        response_format=ToolStrategy(LeadQualificationReport),
    )


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

        result = lead_qualifier.invoke(
            {"messages": [{"role": "user", "content": lead_submission_json}]}
        )
        return structured_or_last_message(result)

    return call_lead_qualifier_agent
