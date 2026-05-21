from __future__ import annotations

from pathlib import Path


def test_speed_to_lead_prompt_requires_compact_mobile_chat_formatting():
    prompt = Path("prompts/speed_to_lead_chat.md").read_text(encoding="utf-8")

    assert "Keep most replies to 2-5 short lines total" in prompt
    assert "Use one compact paragraph when possible" in prompt
    assert "Ask at most 1-2 questions per turn" in prompt
    assert "Do not send dense walls of text" in prompt
    assert "Avoid email-style signatures" in prompt


def test_speed_to_lead_prompt_preserves_budget_and_timeline_context():
    prompt = Path("prompts/speed_to_lead_chat.md").read_text(encoding="utf-8")

    assert "If budget or timeline are already provided" in prompt
    assert "do not ask for them again" in prompt
    assert "Carry those fields forward" in prompt
    assert "briefly reference the known budget and timeline" in prompt


def test_speed_to_lead_prompt_limits_emoji_and_hype():
    prompt = Path("prompts/speed_to_lead_chat.md").read_text(encoding="utf-8")

    assert "Use at most one relevant emoji per message" in prompt
    assert "Avoid hype and guarantees" in prompt
    assert "Do not promise response times" in prompt
