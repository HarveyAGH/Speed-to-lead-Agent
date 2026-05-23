from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.io_helpers as io_helpers
from tools import email


def test_simulated_email_transport_writes_existing_artifact_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(io_helpers, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(email, "EMAIL_TRANSPORT", "simulated")

    result = email.send_customer_email(
        lead_id="lead_123",
        to="maya@example.com",
        subject="Quick follow-up",
        body="Can we talk this week?",
        approval_required=False,
        send_policy="auto_send",
        send_policy_reason="safe clarification",
    )

    artifact = Path(result["sent_email_path"])
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    assert artifact.name == "sent_email.json"
    assert payload["transport"] == "simulated_safe_auto_send"
    assert payload["approval_required"] is False
    assert payload["send_policy"] == "auto_send"
    assert payload["to"] == "maya@example.com"


def test_resend_email_transport_calls_api_and_records_provider_response(
    monkeypatch,
    tmp_path,
):
    calls = []

    def fake_request_json_with_retries(request):
        calls.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "payload": json.loads(request.data.decode("utf-8")),
            }
        )
        return {"id": "email_abc123"}

    monkeypatch.setattr(io_helpers, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(email, "EMAIL_TRANSPORT", "resend")
    monkeypatch.setattr(email, "RESEND_API_KEY", "resend_test_key")
    monkeypatch.setattr(email, "RESEND_FROM_EMAIL", "Owner <owner@example.com>")
    monkeypatch.setattr(email, "RESEND_REPLY_TO_EMAIL", "reply@example.com")
    monkeypatch.setattr(
        email,
        "request_json_with_retries",
        fake_request_json_with_retries,
    )

    result = email.send_customer_email(
        lead_id="lead_123",
        to="maya@example.com",
        subject="Quick follow-up",
        body="Can we talk this week?",
        approval_required=True,
        send_policy="approval_required",
        send_policy_reason="owner approval",
    )

    artifact = Path(result["sent_email_path"])
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    assert calls == [
        {
            "url": email.RESEND_SEND_URL,
            "headers": {
                "Authorization": "Bearer resend_test_key",
                "Content-type": "application/json",
                "User-agent": "speed-to-lead-agent/0.1",
            },
            "payload": {
                "from": "Owner <owner@example.com>",
                "to": ["maya@example.com"],
                "subject": "Quick follow-up",
                "text": "Can we talk this week?",
                "reply_to": "reply@example.com",
            },
        }
    ]
    assert payload["transport"] == "resend"
    assert payload["provider_response"] == {"id": "email_abc123"}


def test_resend_email_transport_requires_provider_configuration(monkeypatch):
    monkeypatch.setattr(email, "EMAIL_TRANSPORT", "resend")
    monkeypatch.setattr(email, "RESEND_API_KEY", "")
    monkeypatch.setattr(email, "RESEND_FROM_EMAIL", "owner@example.com")
    monkeypatch.setattr(email, "RESEND_REPLY_TO_EMAIL", "reply@example.com")

    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        email.send_customer_email(
            lead_id="lead_123",
            to="maya@example.com",
            subject="Quick follow-up",
            body="Can we talk this week?",
        )


def test_unsupported_email_transport_fails_clearly(monkeypatch):
    monkeypatch.setattr(email, "EMAIL_TRANSPORT", "smtp")

    with pytest.raises(ValueError, match="Unsupported EMAIL_TRANSPORT"):
        email.send_customer_email(
            lead_id="lead_123",
            to="maya@example.com",
            subject="Quick follow-up",
            body="Can we talk this week?",
        )
