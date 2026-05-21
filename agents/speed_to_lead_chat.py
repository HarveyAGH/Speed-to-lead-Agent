from __future__ import annotations

from typing import Any

from agents.common import build_structured_chain
from schemas.lead import ChannelConversationDecision


def build_speed_to_lead_chat(model: Any):
    return build_structured_chain(
        model,
        "speed_to_lead_chat.md",
        ChannelConversationDecision,
    )
