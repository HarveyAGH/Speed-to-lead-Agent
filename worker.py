from __future__ import annotations

import argparse
import json
import logging
import time
import traceback
from typing import Any

from langgraph.errors import GraphInterrupt

from app import (
    _latest_agent_run_fields,
    _owner_summary_from_run,
    run_approval_workflow_status,
)
from tools.job_queue import (
    claim_next_lead_job,
    list_recent_jobs,
    mark_lead_job_completed,
    mark_lead_job_failed,
    mark_lead_job_succeeded,
    mark_lead_job_waiting_approval,
    recover_stale_running_jobs,
    setup_job_queue,
)
from tools.airtable_client import update_latest_agent_run_status
from tools.telegram import send_owner_approval_request, send_owner_status_notification


logger = logging.getLogger("lead_worker")


def process_one_job() -> dict[str, Any] | None:
    job = claim_next_lead_job()
    if not job:
        return None

    job_id = job["id"]
    lead_id = job["lead_id"]
    payload = dict(job.get("payload") or {})

    try:
        telegram_result = None
        workflow_state: dict[str, Any] = {}
        try:
            workflow_result = run_approval_workflow_status(lead_id)
            workflow_status = workflow_result["status"]
            workflow_summary = workflow_result["summary"]
            workflow_state = dict(workflow_result.get("state") or {})
        except GraphInterrupt as exc:
            workflow_status = "pending_approval"
            workflow_summary = (
                "The workflow paused at a human approval boundary. "
                f"Interrupt detail: {exc}"
            )

        latest_run = _latest_agent_run_fields(lead_id)
        decision = workflow_state.get("decision") or _decision_from_latest_run(latest_run)
        send_policy = str(
            workflow_state.get("send_policy")
            or decision.get("send_policy")
            or "approval_required"
        )

        if workflow_status == "pending_approval":
            telegram_result = send_owner_approval_request(
                lead_id=lead_id,
                lead_name=str(payload.get("name") or ""),
                company=str(payload.get("company") or ""),
                recommendation=latest_run.get("recommended_next_action")
                or "Review drafted follow-up",
                summary=_owner_summary_from_run(latest_run),
                classification=latest_run.get("classification", ""),
                fit=latest_run.get("fit", ""),
                urgency=latest_run.get("urgency", ""),
                score=latest_run.get("score", ""),
                draft_subject=latest_run.get("draft_subject", ""),
                draft_body=latest_run.get("draft_body", ""),
            )
            if not _notification_delivered(telegram_result):
                raise RuntimeError(
                    "Approval required, but owner Telegram notification failed: "
                    f"{telegram_result}"
                )
            mark_lead_job_waiting_approval(job_id)
        else:
            completion_status = _completion_status_from_state(
                workflow_state=workflow_state,
                send_policy=send_policy,
            )

            if completion_status != "succeeded":
                update_latest_agent_run_status(
                    lead_id=lead_id,
                    approval_status=completion_status,
                )
                mark_lead_job_completed(
                    job_id,
                    completion_status,
                    first_response=completion_status == "auto_sent",
                )
            else:
                mark_lead_job_succeeded(job_id)

            telegram_result = send_owner_status_notification(
                lead_id=lead_id,
                lead_name=str(payload.get("name") or ""),
                company=str(payload.get("company") or ""),
                status=_owner_status_label(completion_status),
                summary=_owner_summary_from_policy(latest_run, decision, completion_status),
                classification=latest_run.get("classification", ""),
                fit=latest_run.get("fit", ""),
                urgency=latest_run.get("urgency", ""),
                score=latest_run.get("score", ""),
                draft_subject=latest_run.get("draft_subject", ""),
                draft_body=latest_run.get("draft_body", ""),
            )

        return {
            "job_id": job_id,
            "lead_id": lead_id,
            "status": workflow_status,
            "summary": workflow_summary,
            "send_policy": send_policy,
            "sent_email": workflow_state.get("sent_email"),
            "telegram": telegram_result,
        }
    except Exception as exc:
        logger.error(
            "job_failed lead_id=%s job_id=%s error=%s",
            lead_id,
            job_id,
            str(exc),
            exc_info=True,
        )
        failure = mark_lead_job_failed(job_id, traceback.format_exc())
        return {
            "job_id": job_id,
            "lead_id": lead_id,
            "status": "failed_or_requeued",
            "error": str(exc),
            "queue": failure,
        }


def run_worker(poll_interval: float) -> None:
    setup_job_queue()
    recover_stale_running_jobs()
    logger.info("Lead worker started. Waiting for queued jobs.")
    while True:
        result = process_one_job()
        if result:
            logger.info("job_result=%s", json.dumps(result, default=str))
            continue
        time.sleep(poll_interval)


def _completion_status_from_state(
    *,
    workflow_state: dict[str, Any],
    send_policy: str,
) -> str:
    final_status = str(workflow_state.get("final_status") or "")
    if final_status == "sent" and send_policy == "auto_send":
        return "auto_sent"
    if final_status == "sent":
        return "approved_sent"
    if final_status == "not_sent":
        return "not_sent"
    return "succeeded"


def _decision_from_latest_run(run_fields: dict[str, Any]) -> dict[str, Any]:
    artifact_paths = run_fields.get("artifact_paths")
    if not artifact_paths:
        return {}

    try:
        paths = json.loads(str(artifact_paths))
        decision_path = paths["decision"]
        with open(decision_path, encoding="utf-8") as handle:
            return json.load(handle)
    except (KeyError, OSError, json.JSONDecodeError):
        return {}


def _owner_status_label(status: str) -> str:
    labels = {
        "auto_sent": "auto-sent safe first response",
        "not_sent": "not sent by policy",
        "succeeded": "workflow completed",
    }
    return labels.get(status, status)


def _owner_summary_from_policy(
    run_fields: dict[str, Any],
    decision: dict[str, Any],
    completion_status: str,
) -> str:
    policy = decision.get("send_policy") or "unknown"
    reason = decision.get("send_policy_reason") or "No policy reason was saved."
    base = _owner_summary_from_run(run_fields)

    if completion_status == "auto_sent":
        return (
            f"{base} The system auto-sent this because send_policy={policy}. "
            f"Reason: {reason}"
        )
    if completion_status == "not_sent":
        return (
            f"{base} The system did not send a customer-facing response because "
            f"send_policy={policy}. Reason: {reason}"
        )
    return base


def _notification_delivered(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    if result.get("configured") is False:
        return False
    return result.get("ok") is not False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Process queued lead intake jobs.")
    parser.add_argument("--once", action="store_true", help="Process one job and exit.")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--list", action="store_true", help="List recent queue jobs and exit.")
    args = parser.parse_args()

    setup_job_queue()

    if args.list:
        for job in list_recent_jobs():
            print(job)
        return 0

    if args.once:
        print(process_one_job() or {"status": "no_pending_jobs"})
        return 0

    run_worker(args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
