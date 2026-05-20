from __future__ import annotations

import pytest
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

    result = app.telegram_webhook(
        {"message": {"text": "hello"}},
        x_telegram_bot_api_secret_token=None,
    )

    assert result == {"ok": True, "ignored": "not_callback_query"}


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
