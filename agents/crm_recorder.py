from __future__ import annotations

from typing import Any


from langchain.tools import tool

from agents.common import build_structured_chain, dump_structured_result, require_json_text
from schemas.lead import CrmNoteReport


def build_crm_recorder(model: Any):
    return build_structured_chain(model, "crm_recorder.md", CrmNoteReport)


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

        result = crm_recorder.invoke({"input": context_json})
        return dump_structured_result(result)

    return call_crm_recorder_agent
