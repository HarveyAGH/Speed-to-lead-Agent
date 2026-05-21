from __future__ import annotations

from tools import channel_crm
from tools.channel_crm import (
    build_channel_lead_fields,
    write_channel_lead_snapshot,
    write_qualified_channel_lead,
)


def test_qualified_raw_status_can_be_stored_as_handoff_without_losing_crm_signal():
    from worker import _stored_conversation_status

    decision = {
        "conversation_status": "qualified_escalate",
        "reply_text": "Great fit. I will hand this to Ahmed.",
    }

    assert decision["conversation_status"] == "qualified_escalate"
    assert _stored_conversation_status(decision) == "qualified_handoff_pending_owner"


def test_build_channel_lead_fields_maps_profile_to_existing_airtable_columns():
    fields = build_channel_lead_fields(
        lead_id="tg_123",
        source_channel="telegram",
        channel_user_id="705",
        sender_name="Snow",
        extracted_profile={
            "business_type": "locksmith company",
            "company_name": "<UNKNOWN>",
            "service_interest": "instant response automation",
            "budget": "$1500 setup plus monthly support",
            "timeline": "this week",
            "website": "<UNKNOWN>",
            "pain_point": "missed emergency lockout leads",
            "lead_volume": "25 per week",
        },
        latest_customer_message="We lose lockout leads because we reply slowly.",
        owner_summary="Qualified locksmith lead.",
        qualification_summary="High urgency and clear ROI.",
        status="qualified_messaging_lead",
    )

    assert fields["lead_id"] == "tg_123"
    assert fields["name"] == "Snow"
    assert fields["company"] == "locksmith company"
    assert fields["source"] == "telegram_message"
    assert fields["service_interest"] == "instant response automation"
    assert fields["budget"] == "$1500 setup plus monthly support"
    assert fields["timeline"] == "this week"
    assert fields["status"] == "qualified_messaging_lead"
    assert "website" not in fields
    assert "Latest customer message" in fields["message"]
    assert "Channel user ID: 705" in fields["message"]


def test_build_channel_lead_fields_can_show_active_messaging_leads():
    fields = build_channel_lead_fields(
        lead_id="wa_123",
        source_channel="whatsapp",
        channel_user_id="15551234567",
        sender_name="Marcus",
        extracted_profile={"business_type": "roofing"},
        latest_customer_message="Hello",
        owner_summary="",
        qualification_summary="",
        status="messaging_active",
    )

    assert fields["lead_id"] == "wa_123"
    assert fields["source"] == "whatsapp_message"
    assert fields["status"] == "messaging_active"
    assert fields["company"] == "roofing"


def test_write_qualified_channel_lead_creates_when_missing(monkeypatch):
    created = {}

    monkeypatch.setattr(channel_crm, "airtable_is_configured", lambda: True)
    monkeypatch.setattr(channel_crm, "find_lead_by_id", lambda lead_id: None)

    def fake_create(fields):
        created.update(fields)
        return {"records": [{"id": "rec_new", "fields": fields}]}

    monkeypatch.setattr(channel_crm, "create_lead", fake_create)

    result = write_qualified_channel_lead(
        lead_id="wa_123",
        source_channel="whatsapp",
        channel_user_id="15551234567",
        sender_name="Marcus",
        extracted_profile={"business_type": "roofing", "budget": "$2000"},
        latest_customer_message="Need faster quote follow-up.",
        owner_summary="Qualified roofing lead.",
        qualification_summary="Clear pain.",
    )

    assert result["action"] == "created"
    assert created["lead_id"] == "wa_123"
    assert created["source"] == "whatsapp_message"


def test_write_qualified_channel_lead_updates_when_existing(monkeypatch):
    updated = {}

    monkeypatch.setattr(channel_crm, "airtable_is_configured", lambda: True)
    monkeypatch.setattr(
        channel_crm,
        "find_lead_by_id",
        lambda lead_id: {"id": "rec_existing", "fields": {"lead_id": lead_id}},
    )

    def fake_update(lead_id, fields):
        updated["lead_id"] = lead_id
        updated["fields"] = fields
        return {"id": "rec_existing", "fields": fields}

    monkeypatch.setattr(channel_crm, "update_lead_fields", fake_update)

    result = write_qualified_channel_lead(
        lead_id="tg_456",
        source_channel="telegram",
        channel_user_id="705",
        sender_name="Elena",
        extracted_profile={"company_name": "Brooks Wellness"},
        latest_customer_message="Need inquiry qualification.",
        owner_summary="Qualified clinic lead.",
        qualification_summary="Good fit.",
    )

    assert result["action"] == "updated"
    assert updated["lead_id"] == "tg_456"
    assert updated["fields"]["company"] == "Brooks Wellness"


def test_write_channel_lead_snapshot_uses_supplied_status(monkeypatch):
    created = {}

    monkeypatch.setattr(channel_crm, "airtable_is_configured", lambda: True)
    monkeypatch.setattr(channel_crm, "find_lead_by_id", lambda lead_id: None)

    def fake_create(fields):
        created.update(fields)
        return {"records": [{"id": "rec_new", "fields": fields}]}

    monkeypatch.setattr(channel_crm, "create_lead", fake_create)

    result = write_channel_lead_snapshot(
        lead_id="wa_789",
        source_channel="whatsapp",
        channel_user_id="15551234567",
        sender_name="Marcus",
        extracted_profile={"business_type": "roofing"},
        latest_customer_message="Need faster storm lead response.",
        status="messaging_active",
    )

    assert result["action"] == "created"
    assert created["status"] == "messaging_active"
