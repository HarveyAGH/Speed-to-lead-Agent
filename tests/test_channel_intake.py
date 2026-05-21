from __future__ import annotations


def test_telegram_text_message_queues_channel_message(monkeypatch):
    from channels.telegram_leads import adapter

    captured = {}

    def fake_ingest_channel_message(**kwargs):
        captured.update(kwargs)
        return {
            "status": "queued",
            "lead_id": "tg_test",
            "conversation_id": 1,
            "job": {"id": 10, "job_type": "channel_message"},
        }

    monkeypatch.setattr(
        "tools.channel_intake.ingest_channel_message",
        fake_ingest_channel_message,
    )

    result = adapter.handle_telegram_lead_message(
        {
            "text": "I need faster lead response for my locksmith company.",
            "chat": {"id": 12345},
            "from": {
                "id": 12345,
                "first_name": "Maya",
                "last_name": "Chen",
                "username": "maya_c",
            },
        }
    )

    assert result["status"] == "queued"
    assert captured == {
        "source_channel": "telegram",
        "channel_user_id": "12345",
        "text": "I need faster lead response for my locksmith company.",
        "sender_name": "Maya Chen",
        "username": "maya_c",
    }


def test_whatsapp_text_message_queues_channel_message(monkeypatch):
    from channels.whatsapp import adapter

    captured = {}

    def fake_ingest_channel_message(**kwargs):
        captured.update(kwargs)
        return {
            "status": "queued",
            "lead_id": "wa_test",
            "conversation_id": 2,
            "job": {"id": 11, "job_type": "channel_message"},
        }

    monkeypatch.setattr(
        "tools.channel_intake.ingest_channel_message",
        fake_ingest_channel_message,
    )

    result = adapter.handle_whatsapp_payload(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [
                                    {
                                        "wa_id": "15551234567",
                                        "profile": {"name": "Daniel Brooks"},
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": "15551234567",
                                        "type": "text",
                                        "text": {
                                            "body": "Can you help us respond to quote requests faster?"
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    )

    assert result == {
        "processed": 1,
        "leads": [
            {
                "status": "queued",
                "lead_id": "wa_test",
                "conversation_id": 2,
                "job": {"id": 11, "job_type": "channel_message"},
            }
        ],
    }
    assert captured == {
        "source_channel": "whatsapp",
        "channel_user_id": "15551234567",
        "text": "Can you help us respond to quote requests faster?",
        "sender_name": "Daniel Brooks",
    }
