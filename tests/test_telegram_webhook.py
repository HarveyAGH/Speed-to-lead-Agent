from __future__ import annotations

import pytest
from fastapi import HTTPException

import app


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
