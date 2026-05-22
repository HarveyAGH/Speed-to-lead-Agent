from __future__ import annotations

from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from tools.airtable_client import find_latest_agent_run_by_lead_id


def latest_agent_run_fields(lead_id: str) -> dict[str, Any]:
    try:
        record = find_latest_agent_run_by_lead_id(lead_id)
    except Exception:
        return {}

    if not record:
        return {}
    return dict(record.get("fields", {}))


def owner_summary_from_run(run_fields: dict[str, Any]) -> str:
    if not run_fields:
        return (
            "The agent processed this lead and paused before customer-facing send. "
            "Review the draft before approving or rejecting."
        )

    classification = run_fields.get("classification") or "unknown"
    fit = run_fields.get("fit") or "unknown"
    urgency = run_fields.get("urgency") or "unknown"
    score = run_fields.get("score") or "not scored"
    action = run_fields.get("recommended_next_action") or "review"

    return (
        f"The agent classified this lead as {classification} with {fit} fit, "
        f"{urgency} urgency, and score {score}. Recommended action: {action}. "
        "Review the draft before approving the customer-facing follow-up."
    )


def graph_interrupt_summary(exc: GraphInterrupt) -> str:
    return (
        "The workflow paused at a human approval boundary. "
        f"Interrupt detail: {exc}"
    )


def run_approval_workflow_status(lead_id: str) -> dict[str, Any]:
    from graph import graph

    config = build_trace_config(
        lead_id=lead_id,
        phase="initial",
        source="tally",
        tags=["webhook", "tally", "lead_intake", "pipeline"],
    )
    result = graph.invoke(
        {"lead_id": lead_id},
        config=config,
    )

    if "__interrupt__" in result:
        return {
            "status": "pending_approval",
            "summary": (
                "The workflow paused at a human approval boundary. "
                f"Interrupt detail: {result['__interrupt__']}"
            ),
            "interrupt": result["__interrupt__"],
        }

    return {
        "status": "completed",
        "summary": result.get("summary", "Workflow Completed."),
        "interrupt": None,
        "state": result,
    }


def resume_lead_send(lead_id: str, decision: str) -> dict[str, Any]:
    from graph import graph

    config = build_trace_config(
        lead_id=lead_id,
        phase=f"approval.{decision}",
        source="telegram",
        tags=["approval", "telegram", "lead_intake", "pipeline"],
        metadata={"decision": decision},
    )

    result = graph.invoke(Command(resume=decision), config=config)

    return {
        "status": decision,
        "lead_id": lead_id,
        "result": result.get("summary", "Workflow resumed."),
        "state": result,
    }


def build_trace_config(
    *,
    lead_id: str,
    phase: str,
    source: str,
    tags: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thread_id = f"lead-{lead_id}"
    base_metadata = {
        "lead_id": lead_id,
        "thread_id": thread_id,
        "source": source,
        "workflow": "speed_to_lead",
        "workflow_phase": phase,
        "workflow_architecture": "explicit_stategraph",
        "checkpoint_backend": "postgres",
    }
    if metadata:
        base_metadata.update(metadata)

    return {
        "configurable": {
            "thread_id": thread_id,
        },
        "run_name": f"speed_to_lead.{phase}.{lead_id}",
        "tags": tags,
        "metadata": base_metadata,
    }
