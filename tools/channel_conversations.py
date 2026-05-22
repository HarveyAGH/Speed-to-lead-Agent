from __future__ import annotations

import json
from threading import Lock
from typing import Any

import psycopg
from psycopg.rows import dict_row

from config import POSTGRES_CONNECT_TIMEOUT_SECONDS, POSTGRES_DB_URI


_setup_lock = Lock()
_setup_done = False

CONVERSATIONS_SQL = """
CREATE TABLE IF NOT EXISTS channel_conversations (
    id BIGSERIAL PRIMARY KEY,
    source_channel TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,
    lead_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    extracted_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_owner_escalated_at TIMESTAMPTZ,
    UNIQUE (source_channel, channel_user_id)
);
"""

MESSAGES_SQL = """
CREATE TABLE IF NOT EXISTS channel_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES channel_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

MESSAGES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_channel_messages_conversation_created
ON channel_messages (conversation_id, created_at);
"""


def setup_channel_conversations() -> None:
    global _setup_done

    if _setup_done:
        return

    with _setup_lock:
        if _setup_done:
            return

        with _connect() as conn:
            conn.execute(CONVERSATIONS_SQL)
            conn.execute(MESSAGES_SQL)
            conn.execute(MESSAGES_INDEX_SQL)

        _setup_done = True


def get_or_create_conversation(
    *,
    source_channel: str,
    channel_user_id: str,
    lead_id: str,
) -> dict[str, Any]:
    setup_channel_conversations()
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO channel_conversations (source_channel, channel_user_id, lead_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_channel, channel_user_id)
            DO UPDATE SET updated_at = now()
            RETURNING id, source_channel, channel_user_id, lead_id, status, extracted_profile, created_at, updated_at, last_owner_escalated_at;
            """,
            (source_channel, channel_user_id, lead_id),
        ).fetchone()
    return dict(row)


def append_channel_message(
    *,
    conversation_id: int,
    role: str,
    content: str,
) -> dict[str, Any]:
    setup_channel_conversations()
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO channel_messages (conversation_id, role, content)
            VALUES (%s, %s, %s)
            RETURNING id, conversation_id, role, content, created_at;
            """,
            (conversation_id, role, content),
        ).fetchone()
    return dict(row)


def get_conversation_context(
    *,
    source_channel: str,
    channel_user_id: str,
    limit: int = 12,
) -> dict[str, Any]:
    setup_channel_conversations()
    with _connect() as conn:
        conversation = conn.execute(
            """
            SELECT id, source_channel, channel_user_id, lead_id, status, extracted_profile, created_at, updated_at, last_owner_escalated_at
            FROM channel_conversations
            WHERE source_channel = %s
              AND channel_user_id = %s
            LIMIT 1;
            """,
            (source_channel, channel_user_id),
        ).fetchone()
        if not conversation:
            return {}

        messages = conn.execute(
            """
            SELECT role, content, created_at
            FROM (
                SELECT role, content, created_at
                FROM channel_messages
                WHERE conversation_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ) recent_messages
            ORDER BY created_at ASC;
            """,
            (conversation["id"], limit),
        ).fetchall()

    context = dict(conversation)
    context["messages"] = [dict(row) for row in messages]
    return context


def update_conversation_state(
    *,
    conversation_id: int,
    extracted_profile: dict[str, Any],
    status: str,
    owner_escalated: bool = False,
) -> dict[str, Any]:
    setup_channel_conversations()
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE channel_conversations
            SET extracted_profile = %s::jsonb,
                status = %s,
                updated_at = now(),
                last_owner_escalated_at = CASE
                    WHEN %s THEN now()
                    ELSE last_owner_escalated_at
                END
            WHERE id = %s
            RETURNING id, source_channel, channel_user_id, lead_id, status, extracted_profile, updated_at, last_owner_escalated_at;
            """,
            (
                json.dumps(extracted_profile),
                status,
                owner_escalated,
                conversation_id,
            ),
        ).fetchone()
    return dict(row)


def mark_conversation_owner_action(
    *,
    lead_id: str,
    action: str,
) -> dict[str, Any]:
    setup_channel_conversations()
    status = _status_for_owner_action(action)
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE channel_conversations
            SET status = %s,
                updated_at = now()
            WHERE lead_id = %s
            RETURNING id, source_channel, channel_user_id, lead_id, status, extracted_profile, updated_at, last_owner_escalated_at;
            """,
            (status, lead_id),
        ).fetchone()

    if not row:
        return {
            "updated": False,
            "lead_id": lead_id,
            "reason": "No channel conversation found for lead_id.",
        }
    return dict(row)


def _status_for_owner_action(action: str) -> str:
    return {
        "take_over": "owner_taking_over",
        "mark_booked": "owner_marked_booked",
        "mark_not_fit": "owner_marked_not_fit",
    }.get(action, "owner_action_recorded")


def _connect():
    if not POSTGRES_DB_URI:
        raise RuntimeError("POSTGRES_DB_URI is required for channel conversations.")
    return psycopg.connect(
        POSTGRES_DB_URI,
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=POSTGRES_CONNECT_TIMEOUT_SECONDS,
    )
