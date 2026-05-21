from __future__ import annotations

import hashlib
import re
from typing import Any

from tools.airtable_client import (
    airtable_is_configured,
    create_lead,
    find_lead_by_id,
    find_latest_agent_run_by_lead_id,
)
from tools.job_queue import (
    enqueue_lead_job,
    find_active_job_by_lead_id,
    find_existing_job_by_fingerprint,
    queue_is_configured,
)

AIRTABLE_LEAD_FIELDS = {
    "lead_id",
    "received_at",
    "name",
    "email",
    "company",
    "role",
    "source",
    "service_interest",
    "message",
    "budget",
    "timeline",
    "website",
    "status",
}


def ingest_lead(lead: dict[str, str]) -> dict[str, Any]:
    if not airtable_is_configured():
        return {
            "status": "error",
            "lead_id": lead["lead_id"],
            "error": "Airtable is not configured",
            "http_status": 500,
        }

    if not queue_is_configured():
        return {
            "status": "error",
            "lead_id": lead["lead_id"],
            "error": "POSTGRES_DB_URI is required for queued processing",
            "http_status": 500,
        }

    existing_lead = find_lead_by_id(lead["lead_id"])
    existing_run = _latest_agent_run_fields(lead["lead_id"]) if existing_lead else {}
    if existing_run:
        return {
            "status": "duplicate_ignored",
            "lead_id": lead["lead_id"],
            "reason": (
                "Lead already has a saved agent run; skipped reprocessing "
                "and notification."
            ),
            "airtable_record": existing_lead,
        }

    lead_fingerprint = build_lead_fingerprint(lead)
    duplicate_job = find_existing_job_by_fingerprint(lead_fingerprint)
    if duplicate_job and duplicate_job["lead_id"] != lead["lead_id"]:
        return {
            "status": "duplicate_fingerprint_ignored",
            "lead_id": lead["lead_id"],
            "reason": (
                "A lead with the same email/company/message fingerprint was "
                "already queued or processed."
            ),
            "duplicate_of": duplicate_job,
        }

    active_job = find_active_job_by_lead_id(lead["lead_id"])
    if active_job:
        return {
            "status": "duplicate_queued",
            "lead_id": lead["lead_id"],
            "reason": "Lead already has a pending or running queue job.",
            "job": active_job,
            "airtable_record": existing_lead,
        }

    airtable_response = (
        {"existing_record": existing_lead}
        if existing_lead
        else create_lead(_airtable_lead_fields(lead))
    )

    job = enqueue_lead_job(
        lead["lead_id"],
        lead,
        lead_fingerprint=lead_fingerprint,
    )

    return {
        "status": "queued",
        "lead_id": lead["lead_id"],
        "airtable_record": airtable_response,
        "job": job,
    }


def build_lead_fingerprint(lead: dict[str, str]) -> str:
    parts = [
        lead.get("email", ""),
        lead.get("company", ""),
        lead.get("service_interest", ""),
        lead.get("message", ""),
        lead.get("website", ""),
    ]
    normalized = "|".join(_normalize_fingerprint_part(part) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_fingerprint_part(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _airtable_lead_fields(lead: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in lead.items()
        if key in AIRTABLE_LEAD_FIELDS and value != ""
    }


def _latest_agent_run_fields(lead_id: str) -> dict[str, Any]:
    try:
        record = find_latest_agent_run_by_lead_id(lead_id)
    except Exception:
        return {}

    if not record:
        return {}
    return dict(record.get("fields", {}))
