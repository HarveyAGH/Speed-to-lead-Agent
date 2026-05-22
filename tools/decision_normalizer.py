from __future__ import annotations

from typing import Any

# Lead classifications saved to CRM and run artifacts.
VALID_CLASSIFICATIONS = {
    "high_intent_sales_call",
    "needs_clarification",
    "bad_fit",
    "spam_or_vendor",
}

# Fit level summarizes how closely the lead matches the target buyer profile.
VALID_FITS = {"high", "medium", "low"}

# Urgency level maps free-text timelines into stable routing choices.
VALID_URGENCIES = {"same_day", "this_week", "low"}

# Recommended business action for the owner or automated first response.
VALID_NEXT_ACTIONS = {
    "book_discovery_call",
    "ask_missing_info",
    "send_pricing_context",
    "nurture",
    "disqualify",
}

# Send policy controls whether the worker sends, asks for approval, or suppresses.
VALID_SEND_POLICIES = {"auto_send", "approval_required", "do_not_send"}

# Response type describes the customer-facing message category for audit/CRM.
VALID_RESPONSE_TYPES = {
    "acknowledgment",
    "qualification_questions",
    "booking_invite",
    "disqualification",
    "none",
}
# Owner alert priority for Telegram notifications.
VALID_OWNER_ALERT_LEVELS = {"urgent", "normal", "none"}

# Sales temperature used for quick owner scanning.
VALID_LEAD_TEMPERATURES = {"hot", "warm", "cold", "spam"}



def normalize_decision(raw: dict[str, Any], fallback_lead_id: str = "") -> dict[str, Any]:
    classification_text = _text(
        raw.get("classification")
        or raw.get("final_classification")
        or raw.get("lead_type")
        or raw.get("status")
    )

    recommended_text = _text(
        raw.get("recommended_next_action")
        or raw.get("recommended_action")
        or raw.get("next_action")
    )

    timeline_text = _text(
        raw.get("timeline")
        or raw.get("lead_timeline")
        or raw.get("requested_timeline")
    )

    classification = _normalize_classification(classification_text)
    fit = _normalize_choice(raw.get("fit"), VALID_FITS, default="medium")
    urgency = _normalize_urgency(
        model_urgency=raw.get("urgency"),
        timeline=timeline_text,
    )
    score = _normalize_score(raw.get("score"))
    next_action = _normalize_next_action(recommended_text, classification_text)
    policy = _derive_send_policy(
        classification=classification,
        fit=fit,
        urgency=urgency,
        score=score,
        next_action=next_action,
    )

    return {
        "lead_id": _text(raw.get("lead_id")) or fallback_lead_id,
        "classification": classification,
        "fit": fit,
        "urgency": urgency,
        "score": score,
        "recommended_next_action": next_action,
        **policy,
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    text = _text(value).lower().replace("-", "_").replace(" ", "_")
    if text in allowed:
        return text
    return default

def _normalize_urgency(model_urgency: Any, timeline: str = "") -> str:
    timeline_text = timeline.lower().replace("-", " ").replace("_", " ")

    same_day_signals = (
        "today",
        "same day",
        "same-day",
        "asap",
        "immediately",
        "right away",
        "now",
        "urgent",
        "emergency",
        "within 24 hours",
        "24 hours",
    )

    this_week_signals = (
        "this week",
        "a week",
        "next few days",
        "few days",
        "within 5 days",
        "5 days",
        "within a week",
    )

    low_signals = (
        "next month",
        "sometime",
        "eventually",
        "not urgent",
        "no rush",
        "later",
        "exploring",
        "researching",
    )

    if any(signal in timeline_text for signal in same_day_signals):
        return "same_day"

    if any(signal in timeline_text for signal in this_week_signals):
        return "this_week"

    if any(signal in timeline_text for signal in low_signals):
        return "low"

    return _normalize_choice(model_urgency, VALID_URGENCIES, default="low")



def _normalize_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return 0

    return max(0, min(100, score))


def _normalize_classification(text: str) -> str:
    lowered = text.lower().replace("-", "_").replace(" ", "_")

    if lowered in VALID_CLASSIFICATIONS:
        return lowered

    if "spam" in lowered or "vendor" in lowered:
        return "spam_or_vendor"

    if "bad" in lowered or "disqual" in lowered or "poor" in lowered:
        return "bad_fit"

    if "clarification" in lowered or "needs_info" in lowered or "missing" in lowered:
        return "needs_clarification"

    if "qualified" in lowered or "high_fit" in lowered or "high_intent" in lowered:
        return "high_intent_sales_call"

    return "needs_clarification"


def _normalize_next_action(text: str, classification_text: str) -> str:
    lowered = text.lower().replace("-", "_").replace(" ", "_")

    if lowered in VALID_NEXT_ACTIONS:
        return lowered

    if "book" in lowered or "call" in lowered or "discovery" in lowered:
        return "book_discovery_call"

    if "missing" in lowered or "clarify" in lowered or "question" in lowered:
        return "ask_missing_info"

    if "price" in lowered or "pricing" in lowered:
        return "send_pricing_context"

    if "nurture" in lowered:
        return "nurture"

    if "disqual" in lowered or "reject" in lowered:
        return "disqualify"

    classification = _normalize_classification(classification_text)
    if classification == "high_intent_sales_call":
        return "book_discovery_call"
    if classification == "needs_clarification":
        return "ask_missing_info"
    if classification in {"bad_fit", "spam_or_vendor"}:
        return "disqualify"

    return "ask_missing_info"


def _derive_send_policy(
    *,
    classification: str,
    fit: str,
    urgency: str,
    score: int,
    next_action: str,
) -> dict[str, str]:
    """Map the business decision into deterministic speed-to-lead behavior."""
    if classification == "spam_or_vendor":
        return {
            "lead_temperature": "spam",
            "send_policy": "do_not_send",
            "response_type": "none",
            "owner_alert_level": "none",
            "send_policy_reason": "Spam or vendor lead; no customer-facing response should be sent.",
        }

    if classification == "bad_fit" or next_action == "disqualify":
        return {
            "lead_temperature": "cold",
            "send_policy": "approval_required",
            "response_type": "disqualification",
            "owner_alert_level": "normal",
            "send_policy_reason": "Legitimate but poor-fit lead; owner should approve any rejection or redirection message.",
        }

    if next_action == "ask_missing_info" or classification == "needs_clarification":
        return {
            "lead_temperature": "warm",
            "send_policy": "auto_send",
            "response_type": "qualification_questions",
            "owner_alert_level": "normal",
            "send_policy_reason": "Low-risk first response asks clarifying questions without pricing, promises, or commitments.",
        }

    if (
        classification == "high_intent_sales_call"
        and next_action == "book_discovery_call"
        and fit == "high"
        and urgency == "same_day"
        and score >= 80
    ):
        return {
            "lead_temperature": "hot",
            "send_policy": "approval_required",
            "response_type": "booking_invite",
            "owner_alert_level": "urgent",
            "send_policy_reason": "Hot lead with booking intent; owner approval protects calendar, tone, and commercial commitments.",
        }

    if next_action == "book_discovery_call":
        return {
            "lead_temperature": "warm",
            "send_policy": "approval_required",
            "response_type": "booking_invite",
            "owner_alert_level": "normal",
            "send_policy_reason": "Booking invite may create expectations; owner should approve before send.",
        }

    if next_action in {"send_pricing_context", "nurture"}:
        return {
            "lead_temperature": "warm",
            "send_policy": "approval_required",
            "response_type": "acknowledgment",
            "owner_alert_level": "normal",
            "send_policy_reason": "Pricing or nurture language can affect positioning; owner approval required.",
        }

    return {
        "lead_temperature": "warm",
        "send_policy": "auto_send",
        "response_type": "acknowledgment",
        "owner_alert_level": "normal",
        "send_policy_reason": "Default safe first response; no high-risk action detected.",
    }
