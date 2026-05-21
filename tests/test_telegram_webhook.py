from __future__ import annotations

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException

import app
from tools.owner_config import get_owner_config


def test_telegram_webhook_rejects_invalid_secret(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as exc_info:
        app.telegram_webhook(
            {"callback_query": {"id": "callback_1", "data": "approve:lead_1"}},
            x_telegram_bot_api_secret_token="wrong-secret",
        )

    assert exc_info.value.status_code == 401


def test_telegram_webhook_ignores_non_callback_update_without_secret(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(app, "TELEGRAM_ALLOW_OWNER_AS_LEAD", False)

    result = app.telegram_webhook(
        {"message": {"text": "hello"}},
        x_telegram_bot_api_secret_token=None,
    )

    assert result == {"ok": True, "ignored": "owner_chat_or_missing_chat"}


def test_telegram_webhook_allows_owner_as_lead_when_test_flag_enabled(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(app, "TELEGRAM_ALLOW_OWNER_AS_LEAD", True)

    def fake_handle(message):
        return {"lead_id": "tg_test", "status": "queued"}

    monkeypatch.setattr(
        "channels.telegram_leads.adapter.handle_telegram_lead_message",
        fake_handle,
    )
    monkeypatch.setattr(
        "channels.telegram_leads.adapter.is_owner_chat",
        lambda chat_id: True,
    )
    monkeypatch.setattr(
        "tools.inbound_events.record_inbound_event",
        lambda source_channel, event_id: True,
    )

    result = app.telegram_webhook(
        {
            "message": {
                "text": "I need faster lead response",
                "chat": {"id": 123},
                "from": {"id": 123},
            }
        },
        x_telegram_bot_api_secret_token=None,
    )

    assert result == {
        "ok": True,
        "lead_intake": {"lead_id": "tg_test", "status": "queued"},
    }


def test_telegram_webhook_ignores_duplicate_lead_message(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(app, "TELEGRAM_ALLOW_OWNER_AS_LEAD", True)
    monkeypatch.setattr(
        "channels.telegram_leads.adapter.is_owner_chat",
        lambda chat_id: True,
    )
    monkeypatch.setattr(
        "tools.inbound_events.record_inbound_event",
        lambda source_channel, event_id: False,
    )

    def fail_if_called(message):
        raise AssertionError("duplicate Telegram updates should not enqueue lead jobs")

    monkeypatch.setattr(
        "channels.telegram_leads.adapter.handle_telegram_lead_message",
        fail_if_called,
    )

    result = app.telegram_webhook(
        {
            "update_id": 123,
            "message": {
                "message_id": 456,
                "text": "I need faster lead response",
                "chat": {"id": 123},
                "from": {"id": 123},
            },
        },
        x_telegram_bot_api_secret_token=None,
    )

    assert result == {"ok": True, "duplicate_ignored": "update:123"}




def test_telegram_webhook_ignores_duplicate_final_status(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(
        app,
        "_latest_agent_run_fields",
        lambda lead_id: {"approval_status": "approved_sent"},
    )
    monkeypatch.setattr(app, "answer_callback_query", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(app, "remove_approval_buttons", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(app, "edit_approval_message", lambda *args, **kwargs: {"ok": True})

    def fail_if_called(*args, **kwargs):
        raise AssertionError("resume_lead_send should not run for duplicate callbacks")

    monkeypatch.setattr(app, "resume_lead_send", fail_if_called)

    result = app.telegram_webhook(
        {
            "callback_query": {
                "id": "callback_1",
                "data": "approve:lead_1",
                "message": {"message_id": 10, "chat": {"id": 20}},
            }
        },
        x_telegram_bot_api_secret_token=None,
    )

    assert result["status"] == "duplicate_callback_ignored"


def test_telegram_webhook_queues_form_approval_background_task(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(app, "_latest_agent_run_fields", lambda lead_id: {})
    monkeypatch.setattr(app, "answer_callback_query", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(app, "remove_approval_buttons", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(app, "edit_approval_message", lambda *args, **kwargs: {"ok": True})

    background_tasks = BackgroundTasks()
    result = app.telegram_webhook(
        {
            "callback_query": {
                "id": "callback_1",
                "data": "approve:lead_1",
                "message": {"message_id": 10, "chat": {"id": 20}},
            }
        },
        background_tasks=background_tasks,
        x_telegram_bot_api_secret_token=None,
    )

    assert result == {
        "ok": True,
        "lead_id": "lead_1",
        "decision": "approve",
        "status": "queued_for_processing",
    }
    assert len(background_tasks.tasks) == 1


def test_telegram_webhook_records_channel_owner_action(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(app, "answer_callback_query", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(app, "edit_approval_message", lambda *args, **kwargs: {"ok": True})

    conversation_updates = {}
    queue_updates = {}
    airtable_updates = {}

    def fake_mark_conversation_owner_action(*, lead_id, action):
        conversation_updates["lead_id"] = lead_id
        conversation_updates["action"] = action
        return {"updated": True, "lead_id": lead_id, "status": "owner_taking_over"}

    def fake_mark_latest_job_status_by_lead_id(*, lead_id, status):
        queue_updates["lead_id"] = lead_id
        queue_updates["status"] = status
        return {"updated": True, "lead_id": lead_id, "status": status}

    def fake_update_lead_fields(*, lead_id, fields):
        airtable_updates["lead_id"] = lead_id
        airtable_updates["fields"] = fields
        return {"id": "rec_test", "fields": fields}

    monkeypatch.setattr(
        app,
        "mark_conversation_owner_action",
        fake_mark_conversation_owner_action,
    )
    monkeypatch.setattr(
        app,
        "mark_latest_job_status_by_lead_id",
        fake_mark_latest_job_status_by_lead_id,
    )
    monkeypatch.setattr(app, "update_lead_fields", fake_update_lead_fields)

    result = app.telegram_webhook(
        {
            "callback_query": {
                "id": "callback_1",
                "data": "channel:take_over:tg_123",
                "message": {"message_id": 10, "chat": {"id": 20}},
            }
        },
        x_telegram_bot_api_secret_token=None,
    )

    assert result["ok"] is True
    assert result["lead_id"] == "tg_123"
    assert result["action"] == "take_over"
    assert result["status"] == "owner_taking_over"
    assert conversation_updates == {"lead_id": "tg_123", "action": "take_over"}
    assert queue_updates == {"lead_id": "tg_123", "status": "owner_taking_over"}
    assert airtable_updates == {
        "lead_id": "tg_123",
        "fields": {"status": "owner_taking_over"},
    }


def test_telegram_webhook_records_channel_mark_booked_action(monkeypatch):
    monkeypatch.setattr(app, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(app, "answer_callback_query", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(app, "edit_approval_message", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(
        app,
        "mark_conversation_owner_action",
        lambda *, lead_id, action: {
            "updated": True,
            "lead_id": lead_id,
            "status": "owner_marked_booked",
        },
    )
    monkeypatch.setattr(
        app,
        "mark_latest_job_status_by_lead_id",
        lambda *, lead_id, status: {
            "updated": True,
            "lead_id": lead_id,
            "status": status,
        },
    )
    monkeypatch.setattr(
        app,
        "update_lead_fields",
        lambda *, lead_id, fields: {"id": "rec_test", "fields": fields},
    )

    result = app.telegram_webhook(
        {
            "callback_query": {
                "id": "callback_1",
                "data": "channel:mark_booked:tg_123",
                "message": {"message_id": 10, "chat": {"id": 20}},
            }
        },
        x_telegram_bot_api_secret_token=None,
    )

    assert result["ok"] is True
    assert result["action"] == "mark_booked"
    assert result["status"] == "owner_marked_booked"


def test_manual_approval_endpoint_requires_management_secret(monkeypatch):
    monkeypatch.setattr(app, "WEBHOOK_SHARED_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as exc_info:
        app.approve_lead_send("lead_1", x_webhook_secret=None)

    assert exc_info.value.status_code == 401


def test_manual_approval_endpoint_accepts_management_secret(monkeypatch):
    monkeypatch.setattr(app, "WEBHOOK_SHARED_SECRET", "expected-secret")
    monkeypatch.setattr(
        app,
        "resume_lead_send",
        lambda lead_id, decision: {
            "status": decision,
            "lead_id": lead_id,
        },
    )

    result = app.approve_lead_send(
        "lead_1",
        x_webhook_secret="expected-secret",
    )

    assert result == {
        "status": "approve",
        "lead_id": "lead_1",
    }


def test_owner_config_loads_default_file():
    get_owner_config.cache_clear()
    config = get_owner_config()

    assert config["owner_name"]
    assert config["business_name"]
