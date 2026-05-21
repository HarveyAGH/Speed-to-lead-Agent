from __future__ import annotations

from tools import airtable_client


def test_find_lead_by_id_escapes_formula_string(monkeypatch):
    captured = {}

    monkeypatch.setattr(airtable_client, "AIRTABLE_API_KEY", "key")
    monkeypatch.setattr(airtable_client, "AIRTABLE_BASE_ID", "base")

    def fake_request(method, table_name, payload=None, query=None):
        captured["query"] = query
        return {"records": []}

    monkeypatch.setattr(airtable_client, "_request", fake_request)

    result = airtable_client.find_lead_by_id("lead_abc'xyz")

    assert result is None
    assert captured["query"]["filterByFormula"] == "{lead_id}='lead_abc\\'xyz'"
