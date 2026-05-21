from __future__ import annotations

from tools.channel_conversations import _status_for_owner_action


def test_status_for_owner_action_maps_supported_actions():
    assert _status_for_owner_action("take_over") == "owner_taking_over"
    assert _status_for_owner_action("mark_booked") == "owner_marked_booked"
    assert _status_for_owner_action("mark_not_fit") == "owner_marked_not_fit"


def test_status_for_owner_action_uses_safe_fallback():
    assert _status_for_owner_action("something_else") == "owner_action_recorded"
