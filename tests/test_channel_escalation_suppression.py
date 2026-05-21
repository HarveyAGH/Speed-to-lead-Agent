from __future__ import annotations

from worker import (
    _airtable_status_for_channel,
    _channel_completion_status,
    _loggable_job_result,
    _should_notify_owner,
)


def test_owner_notification_sends_only_for_first_escalation():
    assert _should_notify_owner(
        owner_escalation_required=True,
        owner_already_escalated=False,
    )

    assert not _should_notify_owner(
        owner_escalation_required=True,
        owner_already_escalated=True,
    )


def test_channel_completion_marks_repeat_escalation_without_owner_notification():
    status = _channel_completion_status(
        {"conversation_status": "qualified_escalate"},
        owner_escalation_required=True,
        owner_already_escalated=True,
        owner_notification_sent=False,
    )

    assert status == "already_escalated_replied"


def test_channel_completion_marks_first_escalation_as_owner_escalated():
    status = _channel_completion_status(
        {"conversation_status": "qualified_escalate"},
        owner_escalation_required=True,
        owner_already_escalated=False,
        owner_notification_sent=True,
    )

    assert status == "owner_escalated"


def test_airtable_status_for_channel_keeps_messaging_leads_visible():
    assert (
        _airtable_status_for_channel(
            raw_conversation_status="continue_conversation",
            stored_conversation_status="continue_conversation",
        )
        == "messaging_active"
    )
    assert (
        _airtable_status_for_channel(
            raw_conversation_status="qualified_escalate",
            stored_conversation_status="qualified_handoff_pending_owner",
        )
        == "qualified_messaging_lead"
    )
    assert (
        _airtable_status_for_channel(
            raw_conversation_status="not_fit_close",
            stored_conversation_status="not_fit_close",
        )
        == "messaging_not_fit"
    )


def test_loggable_job_result_omits_large_nested_payloads():
    compact = _loggable_job_result(
        {
            "job_id": 1,
            "lead_id": "wa_123",
            "job_type": "channel_message",
            "status": "conversation_replied",
            "conversation_status": "continue_conversation",
            "source_channel": "whatsapp",
            "channel_dispatch": {
                "ok": True,
                "result": {"meta_response": {"messages": [{"id": "large"}]}},
            },
            "owner_notification": {
                "ok": True,
                "result": {"text": "very long owner message"},
            },
            "crm_writeback": {"action": "updated", "result": {"large": "payload"}},
        }
    )

    assert compact == {
        "job_id": 1,
        "lead_id": "wa_123",
        "job_type": "channel_message",
        "status": "conversation_replied",
        "conversation_status": "continue_conversation",
        "send_policy": None,
        "source_channel": "whatsapp",
        "channel_dispatch_ok": True,
        "owner_notification_ok": True,
        "crm_action": "updated",
        "queue_status": None,
        "error": None,
    }
