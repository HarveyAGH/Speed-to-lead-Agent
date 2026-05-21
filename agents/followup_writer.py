from __future__ import annotations

from typing import Any

from langchain.tools import tool

from agents.common import build_structured_chain, dump_structured_result, require_json_text
from schemas.lead import FollowupDraft


def build_followup_writer(model: Any):
    return build_structured_chain(model, "followup_writer.md", FollowupDraft)


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

        result = followup_writer.invoke({"input": context_json})
        return dump_structured_result(result)

    return call_followup_writer_agent
