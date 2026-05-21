from __future__ import annotations

from typing import Any

from langchain.tools import tool

from agents.common import build_structured_chain, dump_structured_result, require_json_text
from schemas.lead import MissingInfoReport


def build_missing_info_detector(model: Any):
    return build_structured_chain(model, "missing_info_detector.md", MissingInfoReport)


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

        result = missing_info_detector.invoke({"input": lead_submission_json})
        return dump_structured_result(result)

    return call_missing_info_detector_agent
