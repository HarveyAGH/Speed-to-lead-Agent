from __future__ import annotations

from channels.whatsapp import adapter
from channels.whatsapp.adapter import handle_whatsapp_payload, _verify_meta_signature


def test_verify_meta_signature_accepts_valid_signature():
    body = b"The quick brown fox jumps over the lazy dog"
    secret = "key"
    signature = (
        "sha256="
        "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
    )

    assert _verify_meta_signature(body, secret, signature)


def test_verify_meta_signature_rejects_invalid_signature():
    assert not _verify_meta_signature(b"{}", "app-secret", "sha256=bad")
    assert not _verify_meta_signature(b"{}", "app-secret", "")


def test_whatsapp_payload_ignores_duplicate_message_ids(monkeypatch):
    seen_events = set()
    ingested = []

    def fake_record(message):
        message_id = message["id"]
        if message_id in seen_events:
            return False
        seen_events.add(message_id)
        return True

    def fake_ingest(*, wa_number, text, contact_name=""):
        ingested.append(
            {
                "wa_number": wa_number,
                "text": text,
                "contact_name": contact_name,
            }
        )
        return {"lead_id": "wa_test", "status": "queued"}

    monkeypatch.setattr(adapter, "_record_whatsapp_message_event", fake_record)
    monkeypatch.setattr(adapter, "_ingest_whatsapp_lead", fake_ingest)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {"wa_id": "15551234567", "profile": {"name": "Marcus"}}
                            ],
                            "messages": [
                                {
                                    "id": "wamid.same",
                                    "from": "15551234567",
                                    "type": "text",
                                    "text": {"body": "Hello"},
                                },
                                {
                                    "id": "wamid.same",
                                    "from": "15551234567",
                                    "type": "text",
                                    "text": {"body": "Hello"},
                                },
                            ],
                        }
                    }
                ]
            }
        ]
    }

    result = handle_whatsapp_payload(payload)

    assert result["processed"] == 1
    assert result["duplicates_ignored"] == 1
    assert ingested == [
        {
            "wa_number": "15551234567",
            "text": "Hello",
            "contact_name": "Marcus",
        }
    ]
