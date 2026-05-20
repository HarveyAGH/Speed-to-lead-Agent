from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from config import POSTGRES_DB_URI


STALE_RUNNING_MINUTES = 10

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


def queue_is_configured() -> bool:
    return bool(POSTGRES_DB_URI)


def setup_job_queue() -> None:
    with _connect() as conn:
        conn.execute(JOB_TABLE_SQL)
        conn.execute(JOB_INDEX_SQL)


def enqueue_lead_job(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    setup_job_queue()
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO lead_jobs (lead_id, payload)
            VALUES (%s, %s::jsonb)
            RETURNING id, lead_id, status, attempts, max_attempts, created_at;
            """,
            (lead_id, json.dumps(payload)),
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


def claim_next_lead_job() -> dict[str, Any] | None:
    setup_job_queue()
    recover_stale_running_jobs()
    with _connect() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                SELECT id, lead_id, payload, attempts, max_attempts
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
                RETURNING id, lead_id, payload, attempts, max_attempts;
                """,
                (row["id"],),
            ).fetchone()

    return dict(updated)


def mark_lead_job_succeeded(job_id: int) -> dict[str, Any]:
    return mark_lead_job_completed(job_id, "succeeded")


def mark_lead_job_completed(job_id: int, status: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = %s,
                finished_at = now(),
                updated_at = now(),
                last_error = NULL
            WHERE id = %s
            RETURNING id, lead_id, status, attempts, finished_at;
            """,
            (status, job_id),
        ).fetchone()
    return dict(row)


def mark_lead_job_waiting_approval(job_id: int) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE lead_jobs
            SET status = 'waiting_approval',
                finished_at = now(),
                updated_at = now(),
                last_error = NULL
            WHERE id = %s
            RETURNING id, lead_id, status, attempts, finished_at;
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
                last_error = NULL
            WHERE id = (
                SELECT id
                FROM lead_jobs
                WHERE lead_id = %s
                  AND status = 'waiting_approval'
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING id, lead_id, status, attempts, finished_at;
            """,
            (status, lead_id),
        ).fetchone()

    if not row:
        return {
            "updated": False,
            "lead_id": lead_id,
            "reason": "No waiting_approval queue job found for lead_id.",
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
            SELECT id, lead_id, status, attempts, max_attempts, last_error, created_at, updated_at
            FROM lead_jobs
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _connect():
    if not POSTGRES_DB_URI:
        raise RuntimeError("POSTGRES_DB_URI is required for the lead job queue.")
    return psycopg.connect(POSTGRES_DB_URI, autocommit=True, row_factory=dict_row)
