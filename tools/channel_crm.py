from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tools.airtable_client import (
    airtable_is_configured,
    create_lead,
    find_lead_by_id,
    update_lead_fields,
)


CHANNEL_LEAD_FIELDS = {
    "lead_id",
    "received_at",
    "name",
    "company",
    "role",
    "source",
    "service_interest",
    "message",
    "budget",
    "timeline",
    "website",
    "status",
}


def write_qualified_channel_lead(
    *,
    lead_id: str,
    source_channel: str,
    channel_user_id: str,
    sender_name: str,
    extracted_profile: dict[str, Any],
    latest_customer_message: str,
    owner_summary: str,
    qualification_summary: str,
) -> dict[str, Any]:
    return write_channel_lead_snapshot(
        lead_id=lead_id,
        source_channel=source_channel,
        channel_user_id=channel_user_id,
        sender_name=sender_name,
        extracted_profile=extracted_profile,
        latest_customer_message=latest_customer_message,
        owner_summary=owner_summary,
        qualification_summary=qualification_summary,
        status="qualified_messaging_lead",
    )


def write_channel_lead_snapshot(
    *,
    lead_id: str,
    source_channel: str,
    channel_user_id: str,
    sender_name: str,
    extracted_profile: dict[str, Any],
    latest_customer_message: str,
    owner_summary: str = "",
    qualification_summary: str = "",
    status: str = "messaging_active",
) -> dict[str, Any]:
    fields = build_channel_lead_fields(
        lead_id=lead_id,
        source_channel=source_channel,
        channel_user_id=channel_user_id,
        sender_name=sender_name,
        extracted_profile=extracted_profile,
        latest_customer_message=latest_customer_message,
        owner_summary=owner_summary,
        qualification_summary=qualification_summary,
        status=status,
    )
    if not airtable_is_configured():
        return {"configured": False, "fields": fields}

    existing = find_lead_by_id(lead_id)
    if existing:
        return {
            "action": "updated",
            "result": update_lead_fields(lead_id=lead_id, fields=fields),
        }

    return {
        "action": "created",
        "result": create_lead(fields),
    }


def build_channel_lead_fields(
    *,
    lead_id: str,
    source_channel: str,
    channel_user_id: str,
    sender_name: str,
    extracted_profile: dict[str, Any],
    latest_customer_message: str,
    owner_summary: str,
    qualification_summary: str,
    status: str = "qualified_messaging_lead",
) -> dict[str, Any]:
    business_type = _first_known(extracted_profile.get("business_type"))
    company = _first_known(
        extracted_profile.get("company_name"),
        business_type,
        sender_name,
    )
    service_interest = _first_known(
        extracted_profile.get("service_interest"),
        "Speed-to-lead automation",
    )
    message = _compact_message(
        source_channel=source_channel,
        channel_user_id=channel_user_id,
        latest_customer_message=latest_customer_message,
        extracted_profile=extracted_profile,
        owner_summary=owner_summary,
        qualification_summary=qualification_summary,
    )

    fields = {
        "lead_id": lead_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "name": _first_known(sender_name, "Messaging lead"),
        "company": company,
        "source": f"{source_channel}_message" if source_channel else "message",
        "service_interest": service_interest,
        "message": message,
        "budget": _first_known(extracted_profile.get("budget")),
        "timeline": _first_known(extracted_profile.get("timeline")),
        "website": _first_known(extracted_profile.get("website")),
        "status": status,
    }

    return {
        key: value
        for key, value in fields.items()
        if key in CHANNEL_LEAD_FIELDS and _is_known(value)
    }


def _compact_message(
    *,
    source_channel: str,
    channel_user_id: str,
    latest_customer_message: str,
    extracted_profile: dict[str, Any],
    owner_summary: str,
    qualification_summary: str,
) -> str:
    parts = [
        f"Channel: {source_channel}" if source_channel else "",
        f"Channel user ID: {channel_user_id}" if channel_user_id else "",
        _line("Latest customer message", latest_customer_message),
        _line("Pain point", extracted_profile.get("pain_point")),
        _line("Lead volume", extracted_profile.get("lead_volume")),
        _line("Current tools", extracted_profile.get("current_tools")),
        _line("Team size", extracted_profile.get("team_size")),
        _line("Owner summary", owner_summary),
        _line("Qualification summary", qualification_summary),
    ]
    compact = "\n".join(part for part in parts if _is_known(part))
    return compact[:2000]


def _line(label: str, value: Any) -> str:
    if not _is_known(value):
        return ""
    return f"{label}: {str(value).strip()}"


def _first_known(*values: Any) -> str:
    for value in values:
        if _is_known(value):
            return str(value).strip()
    return ""


def _is_known(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.upper() not in {"<UNKNOWN>", "UNKNOWN", "N/A", "NONE"}
