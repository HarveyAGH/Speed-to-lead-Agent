from __future__ import annotations

from contextlib import ExitStack
from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from agents.supervisor import build_supervisor
from config import POSTGRES_DB_URI


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
    """Build the graph with persistent checkpointing when Postgres is configured.

    InMemorySaver:
    - local demo only
    - state disappears when the Python process stops

    PostgresSaver:
    - stores LangGraph checkpoints in Postgres
    - lets interrupt/resume survive server restarts
    - requires the same thread_id when resuming
    """
    return build_supervisor(checkpointer=get_checkpointer())


graph = build_graph()
