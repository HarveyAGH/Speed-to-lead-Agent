# Technical Audit Brief: AI Speed-to-Lead Agent

This document is written for an external technical reviewer who understands Python, security auditing, and agentic workflows. It explains what this project currently does, how the pieces are wired, what is intentionally simulated, what is already production-shaped, and what is still planned.

## Executive Summary

This repository implements a LangGraph/LangChain supervisor-subagent workflow for a sellable "speed-to-lead" automation product.

The target buyer is a small service business, agency, clinic, or local operator that receives inbound leads and loses revenue when response time is slow or inconsistent.

The current system receives a lead from a Tally form webhook, stores the lead in Airtable, queues background processing in Postgres, invokes a LangGraph supervisor with specialist subagents, saves evidence artifacts, writes run data back to Airtable, determines whether the draft is safe to auto-send or requires owner approval, sends Telegram owner notifications, and resumes approval-gated sends through LangGraph interrupt/resume.

Real integrations currently implemented:

- FastAPI webhook ingestion.
- Tally-compatible payload normalization.
- Airtable lead storage.
- Airtable agent run writeback.
- Postgres-backed background job queue.
- Postgres-backed LangGraph checkpoint persistence.
- Telegram owner notification and approval buttons.
- LangSmith tracing through environment configuration.
- Local evidence artifacts under `outputs/`.

Intentionally simulated:

- Actual customer email transport. "Sending" currently writes a local `sent_email.json` artifact instead of using Resend/Gmail/SMTP. This is deliberate while the system is still being hardened.

## Product Intent

This is not meant to be a general chatbot. It is a workflow automation agent:

```text
inbound lead arrives
-> normalize lead fields
-> save lead in CRM-like table
-> qualify fit/urgency
-> find missing info
-> draft a personalized response
-> save evidence
-> auto-send safe first response OR ask owner for approval
-> log final status
```

The business value is speed-to-lead:

- Respond to inbound leads quickly.
- Avoid generic replies.
- Reduce manual triage.
- Preserve owner control for high-risk messages.
- Produce an audit trail for each agent run.

## High-Level Architecture

```text
Tally form
-> FastAPI /webhooks/tally
-> Airtable Leads row
-> Postgres lead_jobs queue
-> worker.py
-> LangGraph supervisor
-> specialist subagents
-> save artifacts
-> Airtable Agent_runs row
-> deterministic send policy
-> safe auto-send OR Telegram approval
-> simulated sent_email.json
```

## Important Files

### `app.py`

FastAPI entry point.

Main responsibilities:

- `GET /health`: reports whether Airtable, queue, Telegram, and Telegram webhook secret are configured.
- `GET /jobs`: shows recent Postgres queue jobs.
- `POST /webhooks/tally`: receives Tally or flat JSON payloads, normalizes them, stores the lead, and enqueues a background job.
- `POST /telegram/webhook`: receives Telegram callback button events and resumes approval-gated LangGraph runs.
- `POST /approval/{lead_id}/approve` and `/reject`: older manual approval endpoints retained for direct approval tests.
- `normalize_lead_payload`: maps flat payloads or Tally field payloads into the internal lead contract.
- `run_approval_workflow_status`: invokes the graph with a runtime prompt and a stable `thread_id`.
- `resume_lead_send`: resumes a paused LangGraph run using `Command(resume=...)`.

Important behavior:

- The webhook does not run the LLM workflow directly. It only stores the lead and queues a job.
- This avoids long webhook requests and makes the system closer to production behavior.
- Telegram callback requests validate `TELEGRAM_WEBHOOK_SECRET` when configured.

### `worker.py`

Background worker process.

Main responsibilities:

- Claims pending jobs from Postgres.
- Runs the LangGraph workflow.
- Detects whether the graph completed or paused at an approval boundary.
- Sends Telegram approval messages only when approval is needed.
- Executes safe auto-send when `send_policy == "auto_send"`.
- Updates Airtable approval status.
- Updates Postgres job status.

Important statuses:

```text
pending
running
waiting_approval
approved_sent
rejected_by_owner
auto_sent
not_sent
succeeded
failed
```

The worker is where the deterministic business policy is enforced after the LLM has drafted and saved artifacts.

### `graph.py`

Builds the LangGraph runtime.

Current behavior:

- Uses `PostgresSaver` when `POSTGRES_DB_URI` is configured.
- Falls back to `InMemorySaver` for local/demo mode.
- Calls `checkpointer.setup()` for Postgres checkpoint tables.
- Builds the supervisor graph through `build_supervisor(checkpointer=...)`.

Why this matters:

- Postgres checkpointing lets interrupted graph runs survive FastAPI/server restarts.
- Approval resume depends on using the same `thread_id`, currently `lead-{lead_id}`.

### `agents/supervisor.py`

Creates the supervisor agent.

Tools exposed to supervisor:

- `load_lead`
- `lead_qualifier_agent`
- `missing_info_detector_agent`
- `followup_writer_agent`
- `crm_recorder_agent`
- `save_run_artifacts`
- `send_followup_email`

Important design choice:

- The supervisor can call the risky approval-gated send tool.
- The supervisor does **not** own safe auto-send execution. The worker owns it after reading the normalized saved decision.
- This avoids trusting the LLM to remember or enforce the auto-send policy correctly.

### `prompts/supervisor.md`

Supervisor runtime instructions.

The supervisor is told to:

1. Load the lead.
2. Run qualification.
3. Detect missing info.
4. Draft follow-up.
5. Save CRM note.
6. Save artifacts.
7. Use the normalized send policy:
   - `approval_required`: call `send_followup_email`, which interrupts.
   - `auto_send`: do not call the send tool; worker handles safe auto-send.
   - `do_not_send`: do not send.

### `tools/decision_normalizer.py`

Deterministic safety and decision normalization layer.

Purpose:

The LLM may return inconsistent wording. This file converts messy agent output into stable business fields:

```text
classification
fit
urgency
score
recommended_next_action
lead_temperature
send_policy
response_type
owner_alert_level
send_policy_reason
```

Current send policy mapping:

```text
spam_or_vendor
-> do_not_send

bad_fit or disqualify
-> approval_required

needs_clarification or ask_missing_info
-> auto_send

hot high-intent booking lead
-> approval_required

booking invite / pricing / nurture
-> approval_required
```

Why this file is important:

- It is the boundary between LLM reasoning and deterministic business safety.
- It prevents the model from being the only authority on whether a message gets sent.

### `tools/email.py`

Simulated customer-facing email output.

Tools:

- `send_followup_email`: approval-gated send using `interrupt()`.
- `send_safe_followup_email`: non-interrupting safe auto-send for low-risk first responses.

Current transport:

```text
simulated_file_write
simulated_safe_auto_send
```

No real email API is called yet.

### `tools/job_queue.py`

Postgres job queue.

Main responsibilities:

- Create `lead_jobs` table.
- Enqueue jobs.
- Detect active duplicate jobs.
- Claim jobs with `FOR UPDATE SKIP LOCKED`.
- Mark job success, waiting approval, final approval result, or failure.

The queue is separate from LangGraph checkpoint tables. It tracks background work, while LangGraph checkpoint tables track graph state and interrupt/resume data.

### `tools/airtable_client.py`

Airtable API wrapper.

Main responsibilities:

- Find lead by `lead_id`.
- Create lead records.
- Find latest agent run by `lead_id`.
- Create `Agent_runs` records.
- Patch latest run's `approval_status`.

Risk note:

- There is no schema discovery/fallback for missing Airtable columns. If the Airtable table does not contain expected fields, Airtable API calls can fail.

### `tools/telegram.py`

Telegram Bot API wrapper.

Main responsibilities:

- Send approval request with inline Approve/Reject buttons.
- Send status notification without buttons for auto-send/non-approval flows.
- Answer callback queries.
- Remove approval buttons.
- Edit approval messages after approval/rejection.

Current UX:

- Approval messages show classification, fit, urgency, score, recommendation, owner summary, subject, and draft preview.
- Buttons use callback data: `approve:{lead_id}` and `reject:{lead_id}`.

### `tools/crm.py`

Artifact and CRM note writer.

Main responsibilities:

- Save CRM-style markdown note.
- Save:
  - `decision.json`
  - `draft_message.txt`
  - `evidence.json`
- Normalize decision before writing it.
- Create Airtable `Agent_runs` row.

Important:

- `decision.json` contains the normalized send policy.
- The worker reads this artifact to decide safe auto-send vs approval.

### `config.py`

Environment configuration.

Loads `.env` from project root using:

```python
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)
```

Important env vars:

```text
AWS_BEARER_TOKEN_BEDROCK
BEDROCK_MODEL_ID
BEDROCK_REGION
AIRTABLE_API_KEY
AIRTABLE_BASE_ID
AIRTABLE_LEADS_TABLE
AIRTABLE_AGENT_RUNS_TABLE
WEBHOOK_SHARED_SECRET
TELEGRAM_BOT_TOKEN
TELEGRAM_OWNER_CHAT_ID
TELEGRAM_WEBHOOK_SECRET
PUBLIC_BASE_URL
POSTGRES_DB_URI
```

### `tests/`

Current test coverage:

- Lead/mock loading behavior.
- Agency profile required fields.
- Decision normalization and send policy mapping.
- Tally/flat webhook payload normalization.
- Telegram webhook secret rejection.
- Telegram non-callback ignore behavior.
- Duplicate approval callback protection.

Last verified test command:

```bash
.venv/bin/python -m py_compile app.py worker.py graph.py config.py agents/supervisor.py tools/decision_normalizer.py tools/email.py tools/crm.py tools/job_queue.py tools/telegram.py
.venv/bin/python -m pytest
```

Last known result:

```text
15 passed
```

## Data Flow Details

### Intake

1. Tally sends form submission to `/webhooks/tally`.
2. `normalize_lead_payload()` maps labels/fields to internal lead keys.
3. App checks Airtable configuration.
4. App checks Postgres queue configuration.
5. App ignores duplicate leads with saved runs.
6. App ignores duplicate active jobs.
7. App writes/uses Airtable lead record.
8. App enqueues `lead_jobs` row.
9. App returns quickly to Tally.

### Background Processing

1. `worker.py` claims a pending job.
2. Worker invokes `run_approval_workflow_status(lead_id)`.
3. Graph runs supervisor.
4. Supervisor delegates to subagents.
5. Artifacts are saved.
6. If risky send: graph interrupts via `send_followup_email`.
7. If no interrupt: worker reads `decision.json`.
8. Worker applies send policy:
   - `auto_send`: call `send_safe_followup_email`.
   - `do_not_send`: mark no send.
   - default/succeeded: mark complete.
9. Worker sends Telegram status notification or approval request.
10. Worker updates queue status.

### Approval Resume

1. Owner taps Telegram Approve/Reject.
2. Telegram posts callback to `/telegram/webhook`.
3. App validates Telegram secret header when configured.
4. App prevents duplicate final approval actions.
5. App removes buttons.
6. App calls `resume_lead_send(lead_id, decision)`.
7. Graph resumes with `Command(resume=decision)` using the same `thread_id`.
8. If approved, simulated send writes `sent_email.json`.
9. App patches Airtable `approval_status`.
10. App updates queue status.
11. App edits Telegram message to collapsed final status.

## Persistence Model

There are two separate Postgres responsibilities:

### 1. LangGraph checkpoint persistence

Created by `PostgresSaver`.

Tables include:

```text
checkpoints
checkpoint_blobs
checkpoint_writes
checkpoint_migrations
```

Purpose:

- Persist graph state.
- Allow interrupted approval workflows to resume after server restart.

### 2. Application job queue

Created by this app.

Table:

```text
lead_jobs
```

Purpose:

- Track lead processing jobs.
- Avoid webhook timeouts.
- Track running/waiting/final job status.

## Current Production-Like Properties

Already implemented:

- Real external trigger path through Tally/ngrok/FastAPI.
- Fast webhook response using background queue.
- Postgres job queue.
- Postgres LangGraph checkpointer.
- Real Airtable storage.
- Real Telegram approval buttons.
- Same-thread LangGraph resume.
- Deterministic send policy normalizer.
- Safe auto-send path for low-risk clarification replies.
- Approval-gated path for risky sends.
- LangSmith trace metadata/tags.
- Local artifact trail.
- Basic test suite.

## External Audit Response

An external review flagged several issues. This section records what was accepted and what changed.

### Accepted and patched

- Manual `/approval/{lead_id}/approve` and `/reject` endpoints are now protected by `WEBHOOK_SHARED_SECRET` through the `x-webhook-secret` header.
- Stale `running` jobs are now recovered back to `pending` after a threshold so a killed worker does not block a lead forever.
- The worker no longer references `auto_send_result` before assignment in the approval-interrupt path.
- Queue finalization now updates only `waiting_approval` jobs, so a duplicate approval callback cannot overwrite an already terminal `succeeded` job.
- Tally payload normalization now ignores unknown fields instead of turning arbitrary labels into internal keys.
- Lead payload fields are sanitized and length-limited before storage/use.
- CRM/artifact JSON parsing now returns a structured error instead of raising directly on malformed JSON.
- `config.py` no longer overwrites `AWS_BEARER_TOKEN_BEDROCK` with an empty string.
- Regression tests were added for manual approval auth, unknown Tally fields, and lead field sanitization.

### Accepted but still pending

- Artifact paths are still fragmented across separate run directories.
- Airtable and Telegram API calls still need retry/backoff handling.
- Prompt-injection resistance is improved at the payload boundary, but subagent prompts still need explicit untrusted-input rules.
- Context trimming is not implemented yet.
- The Postgres checkpointer is cached through one process-level object; production deployment should confirm connection lifecycle under the target host.
- Telegram callback/resume is still synchronous.

### Needs nuance

- The audit recommendation to switch structured output strategy should not be applied blindly. Bedrock previously failed in this repo with `response_format: Extra inputs are not permitted`, so the safer path is to keep the current tool-compatible flow for now and later test structured-output isolation in a dedicated final synthesis node.
- A raw `StateGraph` may improve visual debuggability, but the current `create_agent` supervisor remains the right complexity level until the product behavior is stable.

## Known Gaps / Audit Targets

These are the most important areas still worth reviewing.

### Security and abuse resistance

- No production authentication around `/webhooks/tally` unless `WEBHOOK_SHARED_SECRET` is configured and sent correctly.
- Telegram webhook secret exists but depends on correct Telegram `setWebhook` configuration.
- Manual `/approval/{lead_id}/approve` and `/reject` endpoints now require `WEBHOOK_SHARED_SECRET`, but they are still secondary legacy endpoints and can likely be removed once Telegram approval is the only owner approval path.
- No rate limiting.
- No request body size limits.
- No IP allowlist.
- No replay protection for webhook payloads.
- Secrets live in `.env`; `.env` must never be committed.

### Reliability

- Stale `running` jobs are automatically recovered to `pending` after the configured threshold.
- Worker is a single process script, not a managed service.
- No dead-letter queue.
- No exponential backoff.
- No idempotency key beyond `lead_id` duplicate checks.
- Airtable failures can requeue jobs depending on where the failure happens.
- Telegram failures are returned but not deeply retried.

### Data correctness

- Airtable schema is assumed.
- Lead identity is `lead_id`; if Tally IDs change or field mappings shift, duplicates can happen.
- Inbound payloads are normalized, unknown Tally fields are ignored, and known fields are sanitized/length-limited. A stricter Pydantic validation layer is still pending.
- `urgency` normalization is currently limited to `same_day`, `this_week`, and `low`.
- Business configuration is still profile/prompt driven, not tenant-aware.

### Agent behavior

- Supervisor still depends on prompt adherence for calling the correct subagents and saving artifacts.
- Decision normalizer makes send policy deterministic, but the draft content itself is still generated by the LLM.
- No automated content safety scanner exists before safe auto-send.
- No LLM eval suite exists yet for draft quality, hallucinated claims, or policy violations.

### Deployment

- Local/ngrok setup only.
- No Dockerfile.
- No Railway/Render/Fly deployment configuration yet.
- No process manager configuration for API + worker.
- No production observability beyond LangSmith and local logs.

### Email

- Real email provider is not connected.
- Resend/Gmail/SMTP integration is intentionally delayed.
- No bounce/error handling.
- No unsubscribe/compliance layer.
- No domain authentication flow.

## What We Are About To Implement Next

Recommended next implementation order:

1. Response-time metrics:
   - Record `received_at`, `queued_at`, `started_at`, `finished_at`, `first_response_at`.
   - Compute speed-to-lead seconds/minutes.
   - Write metrics to Airtable.
   - This is important for selling ROI.

2. Safer auto-send guard:
   - Add deterministic checks before `send_safe_followup_email`.
   - Block auto-send if draft contains pricing, guarantees, discounts, legal claims, calendar commitments, or missing recipient email.

3. Auth hardening:
   - Remove legacy manual `/approval/{lead_id}/...` endpoints once Telegram approval is fully trusted.
   - Require shared secret for Tally webhook.
   - Confirm Telegram secret header is enforced in deployment.
   - Add request size limits and rate limiting at the web layer.

4. Real deployment:
   - Deploy API and worker as separate processes.
   - Use production Postgres.
   - Configure environment variables outside source control.

5. Real email provider:
   - Add Resend or Gmail only after the workflow is stable.
   - Keep simulation until then to avoid wasting free-tier/API quota during debugging.

6. Minimal evals:
   - Add tests for policy-violating drafts.
   - Add fixtures for hot lead, warm lead, bad fit, spam/vendor.
   - Assert expected send policy and final queue state.

7. Multi-client configuration:
   - Move agency profile/business rules toward tenant-specific config.
   - Avoid hardcoding one agency persona forever.

## Suggested Audit Questions

Please evaluate:

1. Are the public endpoints safe enough for an ngrok/public deployment?
2. Is approval resume idempotent enough?
3. Can a malicious third party approve/reject a lead?
4. Is queue status handling correct under worker crash/restart?
5. Can duplicate Tally submissions create duplicate sends?
6. Is the deterministic send policy strict enough?
7. Should safe auto-send require an additional deterministic content scan?
8. Is Airtable interaction sufficiently defensive?
9. Are secrets handled acceptably for the current stage?
10. What should be removed before demoing this to paying clients?

## My Status Rating

I give this a status rating of: **72% production-shaped MVP after the audit-hardening patch**.

Meaning:

- It is much stronger than a local demo because it has real webhook intake, Airtable, Postgres queueing, Postgres checkpointing, Telegram approval, and deterministic send policy.
- It is not yet a production deployment because real email is simulated, response-time metrics are missing, deployment/process management is not finished, external API retries are missing, and deeper prompt-injection/content-safety hardening is still needed.

What is YOUR rating compared to mine? Please give your percentage and explain the top 3 reasons your score differs.
