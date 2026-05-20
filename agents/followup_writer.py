from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.agents.structured_output import ToolStrategy

from agents.common import load_prompt, require_json_text, structured_or_last_message
from schemas.lead import FollowupDraft
from tools.lead_storage import get_agency_profile


def build_followup_writer(model: Any):
    return create_agent(
        model=model,
        tools=[get_agency_profile],
        system_prompt=load_prompt("followup_writer.md"),
        response_format=ToolStrategy(FollowupDraft),
    )


def build_followup_writer_tool(model: Any):
    followup_writer = build_followup_writer(model)

    @tool(
        "followup_writer_agent",
        description=(
            "Writes a personalized agency lead follow-up draft from the lead, "
            "qualification report, missing-info report, and recommended action."
        ),
    )
    def call_followup_writer_agent(context_json: str = "") -> str:
        error = require_json_text(context_json, "context_json")
        if error:
            return error

        result = followup_writer.invoke(
            {"messages": [{"role": "user", "content": context_json}]}
        )
        return structured_or_last_message(result)

    return call_followup_writer_agent
