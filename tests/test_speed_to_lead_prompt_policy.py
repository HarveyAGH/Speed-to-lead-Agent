from __future__ import annotations

from pathlib import Path


def test_prompt_keeps_low_roi_real_businesses_in_nurture_path():
    prompt = Path("prompts/speed_to_lead_chat.md").read_text(encoding="utf-8")

    assert "too early for paid automation" in prompt
    assert "do not hard-close them like spam" in prompt
    assert "owner_escalation_required=false" in prompt
    assert "Do not send the owner's booking link" in prompt
