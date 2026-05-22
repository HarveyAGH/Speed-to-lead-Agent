from __future__ import annotations

from worker import (
    _channel_completion_status,
    _compact_profile,
    _conversation_is_handoff_pending,
    _conversation_is_terminal,
    _customer_is_closing_conversation,
    _message_context,
    _looks_like_nurture_not_ready,
    _reply_text_for_decision,
    _stored_conversation_status,
)


def test_customer_closing_phrases_are_detected_without_llm():
    assert _customer_is_closing_conversation("No thank you")
    assert _customer_is_closing_conversation("all good")
    assert _customer_is_closing_conversation("No thanks, that's all")

    assert not _customer_is_closing_conversation("No, we do not use automation yet")
    assert not _customer_is_closing_conversation("Thanks, my budget is $1500")


def test_terminal_conversation_statuses_do_not_continue():
    assert _conversation_is_terminal("customer_closed")
    assert _conversation_is_terminal("not_fit_close")
    assert _conversation_is_terminal("owner_taking_over")
    assert _conversation_is_terminal("owner_marked_booked")
    assert _conversation_is_terminal("owner_marked_not_fit")

    assert not _conversation_is_terminal("continue_conversation")
    assert not _conversation_is_terminal("qualified_escalate")
    assert not _conversation_is_terminal("qualified_handoff_pending_owner")
    assert _conversation_is_handoff_pending("qualified_handoff_pending_owner")


def test_channel_completion_supports_customer_closed_status():
    status = _channel_completion_status({"conversation_status": "customer_closed"})

    assert status == "customer_closed"


def test_qualified_escalation_is_stored_as_handoff_pending():
    assert (
        _stored_conversation_status({"conversation_status": "qualified_escalate"})
        == "qualified_handoff_pending_owner"
    )


def test_qualified_reply_gets_booking_link(monkeypatch):
    monkeypatch.setattr(
        "worker._discovery_call_url",
        lambda: "https://cal.com/snowaflic/discovery-call",
    )

    reply = _reply_text_for_decision(
        {
            "conversation_status": "qualified_escalate",
            "reply_text": "Great fit. I will get Ahmed to review this.",
        }
    )

    assert "Great fit" in reply
    assert "https://cal.com/snowaflic/discovery-call" in reply


def test_real_business_too_early_does_not_become_terminal_not_fit():
    decision = {
        "conversation_status": "not_fit_close",
        "reply_text": (
            "At $450/month revenue this may be too early for paid automation, "
            "but a starter step could help."
        ),
        "extracted_profile": {
            "business_type": "cleaning company",
            "monthly_revenue": "$450",
            "monthly_inquiry_volume": "6 inquiries",
            "service_interest": "AI automation for customer messaging",
            "website": "none",
        },
    }

    assert _looks_like_nurture_not_ready(decision)
    assert _stored_conversation_status(decision) == "continue_conversation"


def test_nurture_detection_uses_configured_thresholds_not_exact_fixture_strings(monkeypatch):
    monkeypatch.setattr(
        "worker._automation_roi_thresholds",
        lambda: {"min_monthly_revenue": 1000, "min_monthly_leads": 10},
    )
    decision = {
        "conversation_status": "not_fit_close",
        "reply_text": "This may be too early for a paid automation build.",
        "extracted_profile": {
            "business_type": "cleaning company",
            "monthly_revenue": "$500/month",
            "monthly_inquiry_volume": "8 leads monthly",
            "service_interest": "AI automation for customer messaging",
        },
    }

    assert _looks_like_nurture_not_ready(decision)


def test_vendor_pitch_still_closes_as_not_fit():
    decision = {
        "conversation_status": "not_fit_close",
        "reply_text": "We are not interested in backlinks.",
        "extracted_profile": {
            "business_type": "SEO backlinks and guest posts provider",
            "service_offered": "500 backlinks/month",
        },
    }

    assert not _looks_like_nurture_not_ready(decision)
    assert _stored_conversation_status(decision) == "not_fit_close"


def test_bad_fit_generic_respond_language_still_closes(monkeypatch):
    monkeypatch.setattr(
        "worker._automation_roi_thresholds",
        lambda: {"min_monthly_revenue": 1000, "min_monthly_leads": 10},
    )
    decision = {
        "conversation_status": "not_fit_close",
        "reply_text": "We are not the right fit to respond to this request.",
        "qualification_summary": "Bad fit with no relevant service need.",
        "extracted_profile": {
            "business_type": "unknown",
            "monthly_revenue": "$200/month",
            "monthly_inquiry_volume": "2",
        },
    }

    assert not _looks_like_nurture_not_ready(decision)
    assert _stored_conversation_status(decision) == "not_fit_close"


def test_message_context_trims_per_message_and_total_context(monkeypatch):
    monkeypatch.setattr("worker.CHANNEL_MESSAGE_MAX_CHARS", 30)
    monkeypatch.setattr("worker.CHANNEL_CONTEXT_MAX_CHARS", 70)

    messages = [
        {"role": "user", "content": "a" * 100},
        {"role": "assistant", "content": "b" * 100},
        {"role": "user", "content": "c" * 100},
    ]

    context = _message_context(messages)

    assert len(context) <= 3
    assert sum(len(item["content"]) for item in context) <= 70
    assert all(len(item["content"]) <= 30 for item in context)
    assert context[0]["content"].endswith("[truncated]")


def test_compact_profile_caps_accumulated_profile_context(monkeypatch):
    monkeypatch.setattr("worker.CHANNEL_PROFILE_MAX_CHARS", 60)

    profile = {
        "business_type": "roofing company",
        "long_notes": "x" * 200,
        "extra": "should not fully fit",
    }

    compact = _compact_profile(profile)

    assert len(str(compact)) < len(str(profile))
    assert compact.get("_truncated") is True or compact["long_notes"].endswith("[truncated]")
