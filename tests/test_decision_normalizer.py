from __future__ import annotations

from tools.decision_normalizer import normalize_decision


def test_normalize_decision_maps_high_fit_language_to_allowed_values():
    decision = normalize_decision(
        {
            "lead_id": "lead_123",
            "lead_type": "QUALIFIED - HIGH FIT",
            "fit": "High",
            "urgency": "this week",
            "score": "82.4",
            "recommended_action": "book call",
        }
    )

    assert {
        key: decision[key]
        for key in [
            "lead_id",
            "classification",
            "fit",
            "urgency",
            "score",
            "recommended_next_action",
        ]
    } == {
        "lead_id": "lead_123",
        "classification": "high_intent_sales_call",
        "fit": "high",
        "urgency": "this_week",
        "score": 82,
        "recommended_next_action": "book_discovery_call",
    }
    assert decision["send_policy"] == "approval_required"
    assert decision["response_type"] == "booking_invite"


def test_normalize_decision_uses_safe_defaults_for_unknown_values():
    decision = normalize_decision(
        {
            "lead_id": "lead_456",
            "classification": "unknown",
            "fit": "excellent",
            "urgency": "soon",
            "score": "not a number",
            "recommended_next_action": "",
        }
    )

    assert {
        key: decision[key]
        for key in [
            "lead_id",
            "classification",
            "fit",
            "urgency",
            "score",
            "recommended_next_action",
        ]
    } == {
        "lead_id": "lead_456",
        "classification": "needs_clarification",
        "fit": "medium",
        "urgency": "low",
        "score": 0,
        "recommended_next_action": "ask_missing_info",
    }
    assert decision["send_policy"] == "auto_send"
    assert decision["response_type"] == "qualification_questions"


def test_normalize_decision_clamps_score_and_derives_disqualify_action():
    decision = normalize_decision(
        {
            "status": "bad lead disqualify",
            "fit": "low",
            "urgency": "low",
            "score": 140,
            "next_action": "reject",
        },
        fallback_lead_id="lead_fallback",
    )

    assert {
        key: decision[key]
        for key in [
            "lead_id",
            "classification",
            "fit",
            "urgency",
            "score",
            "recommended_next_action",
        ]
    } == {
        "lead_id": "lead_fallback",
        "classification": "bad_fit",
        "fit": "low",
        "urgency": "low",
        "score": 100,
        "recommended_next_action": "disqualify",
    }
    assert decision["send_policy"] == "approval_required"
    assert decision["response_type"] == "disqualification"


def test_normalize_decision_uses_explicit_this_week_timeline_over_model_same_day():
    decision = normalize_decision(
        {
            "lead_id": "lead_timeline",
            "classification": "high_intent_sales_call",
            "fit": "high",
            "urgency": "same_day",
            "timeline": "this week",
            "score": 82,
            "recommended_next_action": "book_discovery_call",
        }
    )

    assert decision["urgency"] == "this_week"
    assert decision["owner_alert_level"] == "normal"


def test_normalize_decision_keeps_same_day_for_explicit_asap_timeline():
    decision = normalize_decision(
        {
            "lead_id": "lead_asap",
            "classification": "high_intent_sales_call",
            "fit": "high",
            "urgency": "this_week",
            "timeline": "ASAP today",
            "score": 82,
            "recommended_next_action": "book_discovery_call",
        }
    )

    assert decision["urgency"] == "same_day"
    assert decision["owner_alert_level"] == "urgent"


def test_normalize_decision_does_not_force_this_month_to_this_week():
    decision = normalize_decision(
        {
            "lead_id": "lead_this_month",
            "classification": "high_intent_sales_call",
            "fit": "high",
            "urgency": "same_day",
            "timeline": "this month",
            "score": 82,
            "recommended_next_action": "book_discovery_call",
        }
    )

    assert decision["urgency"] == "same_day"
    assert decision["owner_alert_level"] == "urgent"


def test_normalize_decision_does_not_force_two_weeks_to_this_week():
    decision = normalize_decision(
        {
            "lead_id": "lead_two_weeks",
            "classification": "high_intent_sales_call",
            "fit": "high",
            "urgency": "low",
            "timeline": "in 2 weeks",
            "score": 82,
            "recommended_next_action": "book_discovery_call",
        }
    )

    assert decision["urgency"] == "low"
    assert decision["owner_alert_level"] == "normal"
