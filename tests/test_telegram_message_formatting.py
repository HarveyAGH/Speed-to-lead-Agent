from __future__ import annotations

from tools.telegram import (
    build_channel_owner_action_markup,
    build_owner_approval_message,
    build_owner_channel_escalation_message,
    build_owner_status_message,
)


def test_owner_approval_message_prioritizes_customer_context_before_decision():
    message = build_owner_approval_message(
        lead_id="lead_test",
        lead_name="Maya Chen",
        company="Clearview Dental",
        recommendation="book_discovery_call",
        summary="High-fit clinic lead with budget and urgency.",
        classification="high_intent_sales_call",
        fit="high",
        urgency="this_week",
        score=92,
        draft_subject="Quick call this week?",
        draft_body="Hi Maya,\n\nThanks for reaching out.",
    )

    assert "Hot lead ready for owner review" in message
    assert "📌 Snapshot" in message
    assert "🧠 Why now" in message
    assert "✉️ Draft preview" in message
    assert "Lead ID: lead_test" in message


def test_channel_escalation_message_shows_customer_quote_and_prioritized_profile():
    message = build_owner_channel_escalation_message(
        lead_id="tg_test",
        source_channel="telegram",
        sender_name="Snow",
        channel_user_id="123",
        owner_summary="High-fit locksmith lead.",
        qualification_summary="25 urgent requests per week and wants this live this week.",
        fit="high",
        urgency="same_day",
        score=92,
        extracted_profile={
            "business_type": "locksmith company",
            "pain_point": "missed emergency lockout leads",
            "lead_volume": "25 emergency lockout requests per week",
            "budget": "$1500 setup + monthly support",
            "timeline": "live this week",
            "website": "<UNKNOWN>",
        },
        transcript=[
            {"role": "customer", "content": "Hello there!"},
            {"role": "assistant", "content": "What brings you here?"},
            {
                "role": "customer",
                "content": "Budget is about $1500 setup plus monthly support.",
            },
        ],
    )

    assert "💬 Customer said" in message
    assert "Budget is about $1500 setup plus monthly support" in message
    assert "🎯 Key details" in message
    assert "Business Type: locksmith company" in message
    assert "<UNKNOWN>" not in message


def test_owner_status_message_uses_outcome_headline():
    message = build_owner_status_message(
        lead_id="lead_test",
        lead_name="Daniel Brooks",
        company="Brooks Roofing",
        status="auto_sent",
        summary="Safe first response was sent.",
        classification="needs_clarification",
        fit="medium",
        urgency="this_week",
        score=62,
        draft_subject="Quick questions",
        draft_body="Hi Daniel,\n\nA few details would help.",
    )

    assert "Safe first response sent" in message
    assert "✉️ Customer-facing message" in message
    assert "📌 Snapshot" in message


def test_channel_escalation_markup_uses_owner_workflow_actions():
    markup = build_channel_owner_action_markup("tg_test")

    buttons = [
        button
        for row in markup["inline_keyboard"]
        for button in row
    ]

    assert buttons == [
        {"text": "✅ I'm handling this", "callback_data": "channel:take_over:tg_test"},
        {
            "text": "📅 Mark booked",
            "callback_data": "channel:mark_booked:tg_test",
        },
        {"text": "❌ Close as not fit", "callback_data": "channel:mark_not_fit:tg_test"},
    ]
