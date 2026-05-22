from __future__ import annotations

from threading import Lock

import psycopg
from psycopg.rows import dict_row

from config import POSTGRES_CONNECT_TIMEOUT_SECONDS, POSTGRES_DB_URI


_setup_lock = Lock()
_setup_done = False

INBOUND_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS inbound_events (
    id BIGSERIAL PRIMARY KEY,
    source_channel TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_channel, event_id)
);
"""


def setup_inbound_events() -> None:
    global _setup_done

    if _setup_done:
        return

    with _setup_lock:
        if _setup_done:
            return

        with _connect() as conn:
            conn.execute(INBOUND_EVENTS_SQL)

        _setup_done = True


def record_inbound_event(source_channel: str, event_id: str) -> bool:
    """Return True for a new inbound event, False for a duplicate delivery."""
    if not event_id:
        return True

    setup_inbound_events()
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO inbound_events (source_channel, event_id)
            VALUES (%s, %s)
            ON CONFLICT (source_channel, event_id) DO NOTHING
            RETURNING id;
            """,
            (source_channel, event_id),
        ).fetchone()

    return row is not None


def _connect():
    if not POSTGRES_DB_URI:
        raise RuntimeError("POSTGRES_DB_URI is required for inbound event tracking.")
    return psycopg.connect(
        POSTGRES_DB_URI,
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=POSTGRES_CONNECT_TIMEOUT_SECONDS,
    )
