from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request

from config import (
    AIRTABLE_AGENT_RUNS_TABLE,
    AIRTABLE_API_KEY,
    AIRTABLE_BASE_ID,
    AIRTABLE_LEADS_TABLE,
)
from tools.http_client import request_json_with_retries


def airtable_is_configured() -> bool:
    return bool(AIRTABLE_API_KEY and AIRTABLE_BASE_ID)


def _request(method: str, table_name: str, payload: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> dict[str, Any]:
    table = quote(table_name, safe="")
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table}"
    if query:
        url = f"{url}?{urlencode(query)}"

    data = None
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = Request(url, data=data, method=method, headers=headers)

    try:
        return request_json_with_retries(request, timeout=20)
    except RuntimeError as exc:
        raise RuntimeError(f"Airtable API request failed: {exc}") from exc


def find_lead_by_id(lead_id: str) -> dict[str, Any] | None:
    if not airtable_is_configured():
        return None

    formula = f"{{lead_id}}='{lead_id}'"
    response = _request(
        "GET",
        AIRTABLE_LEADS_TABLE,
        query={"filterByFormula": formula, "maxRecords": "1"},
    )
    records = response.get("records", [])
    if not records:
        return None
    return records[0]


def find_latest_agent_run_by_lead_id(lead_id: str) -> dict[str, Any] | None:
    if not airtable_is_configured():
        return None

    formula = f"{{lead_id}}='{lead_id}'"
    response = _request(
        "GET",
        AIRTABLE_AGENT_RUNS_TABLE,
        query={
            "filterByFormula": formula,
            "sort[0][field]": "created_at",
            "sort[0][direction]": "desc",
            "maxRecords": "1",
        },
    )
    records = response.get("records", [])
    if not records:
        return None
    return records[0]


def create_agent_run(fields: dict[str, Any]) -> dict[str, Any]:
    if not airtable_is_configured():
        return {"configured": False}

    payload = {"records": [{"fields": fields}]}
    return _request("POST", AIRTABLE_AGENT_RUNS_TABLE, payload=payload)


def create_lead(fields: dict[str, Any]) -> dict[str, Any]:
    if not airtable_is_configured():
        return {"configured": False}

    payload = {"records": [{"fields": fields}]}
    return _request("POST", AIRTABLE_LEADS_TABLE, payload=payload)


def update_lead_fields(
    lead_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if not airtable_is_configured():
        return {"configured": False}

    record = find_lead_by_id(lead_id)
    if not record:
        return {
            "updated": False,
            "lead_id": lead_id,
            "reason": "No Leads record found for lead_id.",
        }

    return _record_request(
        "PATCH",
        AIRTABLE_LEADS_TABLE,
        record["id"],
        payload={"fields": fields},
    )


def _record_request(
    method: str,
    table_name: str,
    record_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    table = quote(table_name, safe="")
    record = quote(record_id, safe="")
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table}/{record}"

    data = None
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = Request(url, data=data, method=method, headers=headers)

    try:
        return request_json_with_retries(request, timeout=20)
    except RuntimeError as exc:
        raise RuntimeError(f"Airtable API request failed: {exc}") from exc


def update_latest_agent_run_fields(
    lead_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if not airtable_is_configured():
        return {"configured": False}

    record = find_latest_agent_run_by_lead_id(lead_id)
    if not record:
        return {
            "updated": False,
            "lead_id": lead_id,
            "reason": "No Agent_runs record found for lead_id.",
        }

    return _record_request(
        "PATCH",
        AIRTABLE_AGENT_RUNS_TABLE,
        record["id"],
        payload={"fields": fields},
    )


def update_latest_agent_run_status(
    lead_id: str,
    approval_status: str,
) -> dict[str, Any]:
    return update_latest_agent_run_fields(
        lead_id=lead_id,
        fields={"approval_status": approval_status},
    )
