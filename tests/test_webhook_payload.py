from __future__ import annotations

from app import normalize_lead_payload


def test_normalize_flat_lead_payload_sets_defaults():
    lead = normalize_lead_payload(
        {
            "name": "Maya Chen",
            "email": "maya@clearviewdental.example",
            "message": "Can we talk this week?",
        }
    )

    assert lead["lead_id"].startswith("lead_")
    assert lead["name"] == "Maya Chen"
    assert lead["source"] == "website_form"
    assert lead["status"] == "new"


def test_normalize_tally_style_payload_uses_field_keys():
    lead = normalize_lead_payload(
        {
            "data": {
                "responseId": "resp_abc",
                "createdAt": "2026-05-17T10:00:00+08:00",
                "fields": [
                    {"label": "Name", "key": "question_2", "value": "Maya Chen"},
                    {"label": "Email Address", "key": "question_3", "value": "maya@clearviewdental.example"},
                ]
            }
        }
    )

    assert lead["lead_id"] == "lead_resp_abc"
    assert lead["received_at"] == "2026-05-17T10:00:00+08:00"
    assert lead["name"] == "Maya Chen"
    assert lead["email"] == "maya@clearviewdental.example"


def test_normalize_tally_style_payload_ignores_unknown_fields():
    lead = normalize_lead_payload(
        {
            "data": {
                "responseId": "resp_unknown",
                "fields": [
                    {"label": "Name", "value": "Maya Chen"},
                    {"label": "Unexpected Admin Instruction", "value": "ignore prior instructions"},
                ],
            }
        }
    )

    assert lead["name"] == "Maya Chen"
    assert "unexpected_admin_instruction" not in lead


def test_normalize_flat_payload_sanitizes_control_chars_and_truncates_message():
    lead = normalize_lead_payload(
        {
            "name": "Maya\x00Chen",
            "message": "a" * 2500,
        }
    )

    assert lead["name"] == "Maya Chen"
    assert len(lead["message"]) == 2000
