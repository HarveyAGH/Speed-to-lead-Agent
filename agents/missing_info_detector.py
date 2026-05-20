from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.agents.structured_output import ToolStrategy

from agents.common import load_prompt, require_json_text, structured_or_last_message
from schemas.lead import MissingInfoReport
from tools.lead_storage import get_agency_profile


def build_missing_info_detector(model: Any):
    return create_agent(
        model=model,
        tools=[get_agency_profile],
        system_prompt=load_prompt("missing_info_detector.md"),
        response_format=ToolStrategy(MissingInfoReport),
    )


def build_missing_info_detector_tool(model: Any):
    missing_info_detector = build_missing_info_detector(model)

    @tool(
        "missing_info_detector_agent",
        description=(
            "Finds missing information needed to qualify or respond to an "
            "inbound lead without making assumptions."
        ),
    )
    def call_missing_info_detector_agent(lead_submission_json: str = "") -> str:
        error = require_json_text(lead_submission_json, "lead_submission_json")
        if error:
            return error

        result = missing_info_detector.invoke(
            {"messages": [{"role": "user", "content": lead_submission_json}]}
        )
        return structured_or_last_message(result)

    return call_missing_info_detector_agent
