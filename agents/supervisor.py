from __future__ import annotations

from typing import Any

from langchain.agents import create_agent

from agents.common import load_prompt
from agents.crm_recorder import build_crm_recorder_tool
from agents.followup_writer import build_followup_writer_tool
from agents.lead_qualifier import build_lead_qualifier_tool
from agents.missing_info_detector import build_missing_info_detector_tool
from config import MODEL
from tools.crm import save_run_artifacts
from tools.email import send_followup_email
from tools.lead_storage import load_lead


def build_supervisor(model: Any = MODEL, checkpointer=None):
    tools = [
        load_lead,
        build_lead_qualifier_tool(model),
        build_missing_info_detector_tool(model),
        build_followup_writer_tool(model),
        build_crm_recorder_tool(model),
        save_run_artifacts,
        send_followup_email,
    ]

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=load_prompt("supervisor.md"),
        checkpointer=checkpointer,
    )
