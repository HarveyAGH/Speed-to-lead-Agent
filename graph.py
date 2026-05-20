from __future__ import annotations

from contextlib import ExitStack
from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from config import POSTGRES_DB_URI
from state import LeadWorkflowState
from workflow_nodes import (
    approval_gate_node,
    detect_missing_node,
    do_not_send_node,
    draft_followup_node,
    final_summary_node,
    load_lead_node,
    qualify_node,
    route_after_approval,
    route_after_save,
    save_artifacts_node,
    save_crm_note_node,
    send_node,
)


_exit_stack = ExitStack()


@lru_cache(maxsize=1)
def get_checkpointer():
    if not POSTGRES_DB_URI:
        return InMemorySaver()

    checkpointer = _exit_stack.enter_context(
        PostgresSaver.from_conn_string(POSTGRES_DB_URI)
    )
    checkpointer.setup()
    return checkpointer


def build_graph():
    builder = StateGraph(LeadWorkflowState)

    builder.add_node("load_lead", load_lead_node)
    builder.add_node("qualify", qualify_node)
    builder.add_node("detect_missing", detect_missing_node)
    builder.add_node("draft_followup", draft_followup_node)
    builder.add_node("save_crm_note", save_crm_note_node)
    builder.add_node("save_artifacts", save_artifacts_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("send", send_node)
    builder.add_node("do_not_send", do_not_send_node)
    builder.add_node("final_summary", final_summary_node)

    builder.add_edge(START, "load_lead")
    builder.add_edge("load_lead", "qualify")
    builder.add_edge("qualify", "detect_missing")
    builder.add_edge("detect_missing", "draft_followup")
    builder.add_edge("draft_followup", "save_crm_note")
    builder.add_edge("save_crm_note", "save_artifacts")

    builder.add_conditional_edges(
        "save_artifacts",
        route_after_save,
        {
            "approval_gate": "approval_gate",
            "send": "send",
            "do_not_send": "do_not_send",
        },
    )

    builder.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "send": "send",
            "do_not_send": "do_not_send",
        },
    )

    builder.add_edge("send", "final_summary")
    builder.add_edge("do_not_send", "final_summary")
    builder.add_edge("final_summary", END)

    return builder.compile(checkpointer=get_checkpointer())


graph = build_graph()
