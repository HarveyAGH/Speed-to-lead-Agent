from __future__ import annotations

import json
from threading import Lock
from typing import Any

import psycopg
from psycopg.rows import dict_row

from config import POSTGRES_DB_URI, STALE_JOB_MINUTES


STALE_RUNNING_MINUTES = STALE_JOB_MINUTES
_queue_setup_lock = Lock()
_queue_setup_done = False

JOB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lead_jobs (
    id BIGSERIAL PRIMARY KEY,
    lead_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
"""

JOB_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_lead_jobs_status_created
ON lead_jobs (status, created_at);
"""

JOB_METRICS_SQL = [
    "ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'form_intake';",
    "ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS owner_notified_at TIMESTAMPTZ;",
    "ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS first_response_at TIMESTAMPTZ;",
    "ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS first_response_status TEXT;",
    "ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS lead_fingerprint TEXT;",
]

JOB_FINGERPRINT_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_lead_jobs_fingerprint
ON lead_jobs (lead_fingerprint, created_at);
"""


def queue_is_configured() -> bool:
    return bool(POSTGRES_DB_URI)


def setup_job_queue() -> None:
    global _queue_setup_done

    if _queue_setup_done:
        return

    with _queue_setup_lock:
        if _queue_setup_done:
            return

        with _connect() as conn:
            conn.execute(JOB_TABLE_SQL)
            conn.execute(JOB_INDEX_SQL)
            for statement in JOB_METRICS_SQL:
                conn.execute(statement)
            conn.execute(JOB_FINGERPRINT_INDEX_SQL)

        _queue_setup_done = True


def enqueue_lead_job(
    lead_id: str,
    payload: dict[str, Any],
    *,
    lead_fingerprint: str = "",
    job_type: str = "form_intake",
) -> dict[str, Any]:
    setup_job_queue()
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO lead_jobs (lead_id, payload, lead_fingerprint, job_type)
            VALUES (%s, %s::jsonb, NULLIF(%s, ''), %s)
            RETURNING id, lead_id, status, attempts, max_attempts, lead_fingerprint, job_type, created_at;
            """,
            (lead_id, json.dumps(payload), lead_fingerprint, job_type),
        ).fetchone()
    return dict(row)


def find_active_job_by_lead_id(
    lead_id: str,
    stale_after_minutes: int = STALE_RUNNING_MINUTES,
) -> dict[str, Any] | None:
    setup_job_queue()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, lead_id, status, attempts, max_attempts, last_error, created_at, updated_at
            FROM lead_jobs
            WHERE lead_id = %s
              AND (
                status IN ('pending', 'waiting_approval')
                OR (
                    status = 'running'
                    AND updated_at >= now() - (%s * interval '1 minute')
                )
              )
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (lead_id, stale_after_minutes),
        ).fetchone()
    return dict(row) if row else None


def find_existing_job_by_fingerprint(
    lead_fingerprint: str,
) -> dict[str, Any] | None:
    if not lead_fingerprint:
        return None

    setup_job_queue()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, lead_id, status, attempts, max_attempts, last_error, created_at, updated_at
            FROM lead_jobs
            WHERE lead_fingerprint = %s
              AND status IN (
                'pending',
                'running',
                'waiting_approval',
                'auto_sent',
                'approved_sent',
                'succeeded',
                'not_sent'
              )
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (lead_fingerprint,),
        ).fetchone()
    return dict(row) if row else None


def claim_next_lead_job() -> dict[str, Any] | None:
    setup_job_queue()
    recover_stale_running_jobs()
    with _connect() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                SELECT id, lead_id, payload, attempts, max_attempts, job_type
                FROM lead_jobs
                WHERE status = 'pending'
                  AND attempts < max_attempts
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1;
                """
            ).fetchone()

            if not row:
                return None

            updated = conn.execute(
                """
                UPDATE lead_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = now(),
                    updated_at = now()
                WHERE id = %s
                RETURNING id, lead_id, payload, attempts, max_attempts, job_type;
                """,
                (row["id"],),
            ).fetchone()

    return dict(updated)


def mark_lead_job_succeeded(job_id: int) -> dict[str, Any]:
    return mark_lead_job_completed(job_id, "succeeded")


def mark_lead_job_completed(
    job_id: int,
    status: str,
    *,
    first_response: bool = False,
) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = %s,
                finished_at = now(),
                updated_at = now(),
                last_error = NULL,
                first_response_at = CASE
                    WHEN %s THEN COALESCE(first_response_at, now())
                    ELSE first_response_at
                END,
                first_response_status = CASE
                    WHEN %s THEN %s
                    ELSE first_response_status
                END
            WHERE id = %s
            RETURNING id, lead_id, status, attempts, finished_at, first_response_at, first_response_status;
            """,
            (status, first_response, first_response, status, job_id),
        ).fetchone()
    return dict(row)


def mark_lead_job_waiting_approval(job_id: int) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = 'waiting_approval',
                owner_notified_at = COALESCE(owner_notified_at, now()),
                updated_at = now(),
                last_error = NULL
            WHERE id = %s
            RETURNING id, lead_id, status, attempts, owner_notified_at;
            """,
            (job_id,),
        ).fetchone()
    return dict(row)


def mark_latest_waiting_job_resolved(lead_id: str, status: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = %s,
                finished_at = now(),
                updated_at = now(),
                last_error = NULL,
                first_response_at = CASE
                    WHEN %s THEN COALESCE(first_response_at, now())
                    ELSE first_response_at
                END,
                first_response_status = CASE
                    WHEN %s THEN %s
                    ELSE first_response_status
                END
            WHERE id = (
                SELECT id
                FROM lead_jobs
                WHERE lead_id = %s
                  AND status = 'waiting_approval'
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING id, lead_id, status, attempts, finished_at, first_response_at, first_response_status;
            """,
            (
                status,
                status == "approved_sent",
                status == "approved_sent",
                status,
                lead_id,
            ),
        ).fetchone()

    if not row:
        return {
            "updated": False,
            "lead_id": lead_id,
            "reason": "No waiting_approval queue job found for lead_id.",
        }
    return dict(row)


def claim_waiting_approval_job(
    lead_id: str,
    decision: str,
) -> dict[str, Any] | None:
    setup_job_queue()
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = 'approval_processing',
                payload = jsonb_set(
                    payload,
                    '{approval_decision}',
                    to_jsonb(%s::text),
                    true
                ),
                updated_at = now()
            WHERE id = (
                SELECT id
                FROM lead_jobs
                WHERE lead_id = %s
                  AND status = 'waiting_approval'
                ORDER BY created_at DESC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, lead_id, status, attempts, payload, updated_at;
            """,
            (decision, lead_id),
        ).fetchone()

    return dict(row) if row else None


def mark_latest_job_status_by_lead_id(lead_id: str, status: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = %s,
                finished_at = COALESCE(finished_at, now()),
                updated_at = now(),
                last_error = NULL
            WHERE id = (
                SELECT id
                FROM lead_jobs
                WHERE lead_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING id, lead_id, status, attempts, finished_at, first_response_at, first_response_status;
            """,
            (status, lead_id),
        ).fetchone()

    if not row:
        return {
            "updated": False,
            "lead_id": lead_id,
            "reason": "No queue job found for lead_id.",
        }
    return dict(row)


def recover_stale_running_jobs(
    stale_after_minutes: int = STALE_RUNNING_MINUTES,
) -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            """
            UPDATE lead_jobs
            SET status = 'pending',
                last_error = 'recovered_from_stale_running',
                updated_at = now()
            WHERE status = 'running'
              AND updated_at < now() - (%s * interval '1 minute')
              AND attempts < max_attempts
            RETURNING id, lead_id, status, attempts, last_error;
            """,
            (stale_after_minutes,),
        ).fetchall()

    return {
        "recovered": len(rows),
        "jobs": [dict(row) for row in rows],
    }


def mark_lead_job_failed(job_id: int, error: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = CASE
                    WHEN attempts >= max_attempts THEN 'failed'
                    ELSE 'pending'
                END,
                last_error = %s,
                updated_at = now(),
                finished_at = CASE
                    WHEN attempts >= max_attempts THEN now()
                    ELSE finished_at
                END
            WHERE id = %s
            RETURNING id, lead_id, status, attempts, max_attempts, last_error;
            """,
            (error[:4000], job_id),
        ).fetchone()
    return dict(row)


def list_recent_jobs(limit: int = 10) -> list[dict[str, Any]]:
    setup_job_queue()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                lead_id,
                job_type,
                status,
                attempts,
                max_attempts,
                last_error,
                created_at,
                updated_at,
                started_at,
                owner_notified_at,
                first_response_at,
                first_response_status,
                CASE
                    WHEN started_at IS NULL THEN NULL
                    ELSE EXTRACT(EPOCH FROM (started_at - created_at))::INTEGER
                END AS queue_wait_seconds,
                CASE
                    WHEN owner_notified_at IS NULL THEN NULL
                    ELSE EXTRACT(EPOCH FROM (owner_notified_at - created_at))::INTEGER
                END AS owner_notification_seconds,
                CASE
                    WHEN first_response_at IS NULL THEN NULL
                    ELSE EXTRACT(EPOCH FROM (first_response_at - created_at))::INTEGER
                END AS first_response_seconds
            FROM lead_jobs
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_job_payload_by_lead_id(lead_id: str) -> dict[str, Any]:
    setup_job_queue()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT payload
            FROM lead_jobs
            WHERE lead_id = %s
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (lead_id,),
        ).fetchone()

    if not row:
        return {}
    return dict(row.get("payload") or {})


def _connect():
    if not POSTGRES_DB_URI:
        raise RuntimeError("POSTGRES_DB_URI is required for the lead job queue.")
    return psycopg.connect(POSTGRES_DB_URI, autocommit=True, row_factory=dict_row)
