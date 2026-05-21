from __future__ import annotations

from typing import Any


from langchain.agents import create_agent
from langchain.tools import tool
from langchain.agents.structured_output import ToolStrategy

from agents.common import load_prompt, require_json_text, structured_or_last_message
from schemas.lead import CrmNoteReport


def build_crm_recorder(model: Any):
    return create_agent(
        model=model,
        tools=[],
        system_prompt=load_prompt("crm_recorder.md"),
        response_format=ToolStrategy(CrmNoteReport),
    )


def build_crm_recorder_tool(model: Any):
    crm_recorder = build_crm_recorder(model)

    @tool(
        "crm_recorder_agent",
        description=(
            "Creates and saves a CRM-style note for a lead based on structured "
            "qualification, missing-info, and follow-up draft context."
        ),
    )
    def call_crm_recorder_agent(context_json: str = "") -> str:
        error = require_json_text(context_json, "context_json")
        if error:
            return error

        result = crm_recorder.invoke(
            {"messages": [{"role": "user", "content": context_json}]}
        )
        return structured_or_last_message(result)

    return call_crm_recorder_agent
