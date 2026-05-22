from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import tools.crm as crm
import tools.channel_conversations as channel_conversations
import tools.io_helpers as io_helpers
import tools.inbound_events as inbound_events
import tools.job_queue as job_queue
from tools.crm import save_run_artifacts
from workflow_nodes import (
    _draft_summary,
    _extract_structured_dict,
    _lead_context,
    _qualification_summary,
)


def test_extract_structured_dict_rejects_unparseable_agent_output():
    with pytest.raises(ValueError, match="returned unparseable output"):
        _extract_structured_dict(
            {"messages": [AIMessage(content="this is not structured json")]},
            "test_agent",
        )


def test_save_run_artifacts_writes_crm_note_in_same_run_folder(monkeypatch, tmp_path):
    def fake_output_run_dir(run_id: str) -> Path:
        path = tmp_path / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(crm, "output_run_dir", fake_output_run_dir)
    monkeypatch.setattr(crm, "airtable_is_configured", lambda: False)

    raw = save_run_artifacts(
        lead_id="lead_test",
        decision_json=json.dumps(
            {
                "lead_id": "lead_test",
                "classification": "needs_clarification",
                "fit": "medium",
                "urgency": "this_week",
                "score": 62,
                "recommended_next_action": "ask_missing_info",
            }
        ),
        draft_subject="Test subject",
        draft_body="Test body",
        evidence_json=json.dumps({"signals": ["test"]}),
        crm_note_json=json.dumps(
            {
                "lead_id": "lead_test",
                "crm_status": "needs_clarification",
                "note_path": "",
                "summary": "Owner-facing summary.",
                "saved_fields": ["lead_id", "crm_status", "summary"],
            }
        ),
    )

    result = json.loads(raw)
    paths = result["paths"]
    run_dirs = {Path(path).parent for path in paths.values()}

    assert set(paths) == {"decision", "draft", "evidence", "crm_note"}
    assert len(run_dirs) == 1
    assert Path(paths["crm_note"]).read_text(encoding="utf-8").startswith("# CRM Note")


def test_output_run_dir_rejects_path_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(io_helpers, "OUTPUT_DIR", tmp_path / "outputs")

    with pytest.raises(ValueError, match="escapes OUTPUT_DIR"):
        io_helpers.output_run_dir("../../tmp/evil")


def test_save_run_artifacts_sanitizes_malicious_lead_id(monkeypatch, tmp_path):
    monkeypatch.setattr(io_helpers, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(crm, "airtable_is_configured", lambda: False)

    raw = save_run_artifacts(
        lead_id="../../tmp/evil",
        decision_json=json.dumps(
            {
                "lead_id": "../../tmp/evil",
                "classification": "needs_clarification",
                "fit": "medium",
                "urgency": "this_week",
                "score": 62,
                "recommended_next_action": "ask_missing_info",
            }
        ),
        draft_subject="Test subject",
        draft_body="Test body",
        evidence_json=json.dumps({"signals": ["test"]}),
    )

    result = json.loads(raw)
    output_root = (tmp_path / "outputs").resolve()
    run_dir = Path(result["paths"]["decision"]).parent.resolve()

    assert output_root in run_dir.parents
    assert ".." not in result["run_id"]
    assert "/" not in result["run_id"]
    assert "\\" not in result["run_id"]


def test_lead_context_removes_internal_airtable_fields_and_truncates_long_message():
    context = _lead_context(
        {
            "lead_id": "lead_test",
            "email": "test@example.com",
            "message": "x" * 1300,
            "_airtable_record_id": "rec_hidden",
            "_source": "airtable",
        }
    )

    assert "_airtable_record_id" not in context
    assert "_source" not in context
    assert context["message"].endswith("...[truncated]")


def test_qualification_summary_drops_verbose_evidence_list():
    summary = _qualification_summary(
        {
            "lead_id": "lead_test",
            "lead_type": "high_intent_sales_call",
            "fit": "high",
            "urgency": "this_week",
            "score": 82,
            "recommended_next_action": "book_discovery_call",
            "rationale": "good fit",
            "evidence": [{"field": "message", "value": "large", "interpretation": "large"}],
        }
    )

    assert summary["lead_type"] == "high_intent_sales_call"
    assert "evidence" not in summary


def test_draft_summary_uses_preview_instead_of_full_body():
    summary = _draft_summary(
        {
            "lead_id": "lead_test",
            "recipient_email": "test@example.com",
            "subject": "Subject",
            "body": "a" * 900,
            "approval_required": True,
            "reason_approval_required": "booking invite",
        }
    )

    assert "body" not in summary
    assert summary["body_preview"].endswith("...[truncated]")


def test_worker_imports_workflow_runner_instead_of_app():
    source = Path("worker.py").read_text(encoding="utf-8")

    assert "from app import" not in source
    assert "import app" not in source
    assert "from tools.workflow_runner import" in source
    assert "_latest_agent_run_fields" not in source
    assert "_owner_summary_from_run" not in source


def test_workflow_runner_exports_public_helper_names():
    source = Path("tools/workflow_runner.py").read_text(encoding="utf-8")

    assert "_latest_agent_run_fields =" not in source
    assert "_owner_summary_from_run =" not in source
    assert "def latest_agent_run_fields" in source
    assert "def owner_summary_from_run" in source


def test_artifact_and_email_helpers_are_plain_functions():
    crm_source = Path("tools/crm.py").read_text(encoding="utf-8")
    email_source = Path("tools/email.py").read_text(encoding="utf-8")

    assert "@tool" not in crm_source
    assert "send_followup_email" not in email_source
    assert "send_safe_followup_email" not in email_source
    assert "def write_sent_email_artifact" in email_source


def test_stale_recovery_includes_approval_processing_jobs():
    source = Path("tools/job_queue.py").read_text(encoding="utf-8")

    assert "approval_processing" in source
    assert "THEN 'waiting_approval'" in source
    assert "recovered_from_stale_approval_processing" in source


def test_postgres_connectors_use_timeout(monkeypatch):
    calls = []

    def fake_connect(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop after capture")

    for module in (job_queue, channel_conversations, inbound_events):
        monkeypatch.setattr(module, "POSTGRES_DB_URI", "postgresql://example")
        monkeypatch.setattr(module, "POSTGRES_CONNECT_TIMEOUT_SECONDS", 7)
        monkeypatch.setattr(module.psycopg, "connect", fake_connect)

        with pytest.raises(RuntimeError, match="stop after capture"):
            module._connect()

    assert calls
    assert all(call["connect_timeout"] == 7 for call in calls)


def test_checkpointer_uses_temporary_exit_stack_before_global_stack():
    source = Path("graph.py").read_text(encoding="utf-8")

    assert "with ExitStack() as setup_stack:" in source
    assert "setup_stack.enter_context" in source
    assert "_exit_stack.enter_context(setup_stack.pop_all())" in source
