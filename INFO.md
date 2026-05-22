# Technical Audit Brief: AI Speed-to-Lead Agent

This document is written for an external technical reviewer who understands Python, security auditing, and agentic workflows. It explains what this project currently does, how the pieces are wired, what is intentionally simulated, what is already production-shaped, and what is still planned.

## Executive Summary

This repository implements a LangGraph `StateGraph` workflow plus messaging-channel intake for a sellable "speed-to-lead" automation product.

The target buyer is a small service business, agency, clinic, or local operator that receives inbound leads and loses revenue when response time is slow or inconsistent.

The current system receives structured leads from a Tally form webhook and live conversational leads from Telegram or WhatsApp. It stores leads in Airtable, queues background processing in Postgres, invokes the appropriate workflow in a worker process, saves evidence artifacts, writes run or messaging snapshots back to Airtable, sends chat-native customer replies, alerts the owner through Telegram when a lead needs human handoff, and resumes approval-gated form sends through LangGraph interrupt/resume.

Latest v4 audit hardening now implemented:

- Channel conversations cap per-message context and total recent-message context before LLM calls.
- Accumulated extracted profiles are compacted before being passed back into the chat agent.
- Telegram form-approval callbacks return quickly and offload graph resume to FastAPI background tasks.
- WhatsApp Meta signature verification uses `hmac.digest(...)` and is covered by a known HMAC-SHA256 test vector.
- Airtable formula filters escape lead IDs before interpolation.
- LLM retry behavior has one retry boundary at the structured-chain layer instead of nested model + chain retries.
- Conversation-message ordering is chronological at the SQL query level.
- Automation nurture thresholds are configurable in `agency_profile.json` instead of hardcoded to one fixture.
- Airtable messaging snapshots mark long CRM messages with `...[truncated]`.

Real integrations currently implemented:

- FastAPI webhook ingestion.
- Tally-compatible payload normalization.
- Airtable lead storage.
- Airtable agent run writeback.
- Postgres-backed background job queue.
- Postgres-backed LangGraph checkpoint persistence.
- Telegram owner notification and approval buttons.
- WhatsApp inbound/outbound messaging through Meta Cloud API.
- Telegram lead intake through the existing bot.
- Postgres conversation storage for messaging channels.
- Inbound webhook duplicate-event tracking.
- LangSmith tracing through environment configuration.
- Local evidence artifacts under `outputs/`.

Intentionally simulated / still out of scope:

- Customer email defaults to simulated `sent_email.json` artifacts for local/dev safety. Production email delivery is now available only when `EMAIL_TRANSPORT=resend` and Resend credentials are configured.
- Production deployment/process management. The project is still local/ngrok oriented until the next deployment phase.
- Full operational monitoring dashboard. Current visibility is `/health`, `/jobs`, LangSmith, Airtable rows, Postgres queries, and compact worker logs.

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
-> LangGraph StateGraph pipeline
-> specialist LLM nodes
-> save artifacts
-> Airtable Agent_runs row
-> deterministic send policy
-> safe auto-send OR Telegram approval
-> simulated or Resend sent_email.json metadata
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
- Builds an explicit `StateGraph` with nodes for lead loading, qualification, missing-info detection, follow-up drafting, CRM note saving, artifact saving, approval gating, sending, and final summary.

Why this matters:

- Postgres checkpointing lets interrupted graph runs survive FastAPI/server restarts.
- Approval resume depends on using the same `thread_id`, currently `lead-{lead_id}`.

### `workflow_nodes.py`

Contains the node functions used by `graph.py`.

Important nodes:

- `load_lead_node`
- `qualify_node`
- `detect_missing_node`
- `draft_followup_node`
- `save_crm_note_node`
- `save_artifacts_node`
- `approval_gate_node`
- `send_node`
- `do_not_send_node`
- `final_summary_node`

Important design choice:

- The LLM is used for judgment-heavy work only.
- Routing is deterministic through graph edges and `decision_normalizer.py`.
- Risky customer-facing sends pause at `approval_gate_node`.
- Safe sends go through `send_node` without requiring owner approval.
- `send_node` calls `send_customer_email`, which dispatches to simulated artifact mode or Resend based on `EMAIL_TRANSPORT`.

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

Customer-facing email transport boundary.

Main functions:

- `send_customer_email`: dispatches to the configured transport.
- `write_sent_email_artifact`: records the send artifact for simulated and provider-backed sends.

Current transports:

```text
simulated
simulated_safe_auto_send
simulated_approved_send
resend
```

Resend calls use the shared retrying HTTP helper and record provider response metadata in `sent_email.json`.

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

- Save CRM-style markdown note into the same canonical run folder as the other artifacts.
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
- Manual approval endpoint secret enforcement.
- HTTP retry/backoff behavior.
- Public POST guardrail helper behavior.

Last verified test command:

```bash
.venv/bin/python -m py_compile app.py worker.py graph.py workflow_nodes.py config.py tools/decision_normalizer.py tools/email.py tools/crm.py tools/job_queue.py tools/telegram.py tools/airtable_client.py tools/http_client.py
.venv/bin/python -m pytest
```

Last known result:

```text
85 passed
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
6. If risky send: graph interrupts at `approval_gate_node`.
7. If no interrupt: worker reads `decision.json`.
8. Worker applies send policy:
   - `auto_send`: graph calls `send_customer_email`.
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
8. If approved, `send_customer_email` writes `sent_email.json` and sends through Resend only when explicitly configured.
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
- Postgres queue metrics for queue wait, owner notification, and first response timing.
- Request size and in-process rate guardrails for public POST endpoints.
- Retry/backoff wrapper for Airtable and Telegram API calls.
- Explicit untrusted-input rules in supervisor and subagent prompts.
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
- External API calls have bounded retry/backoff, but there is no dead-letter queue for repeated Airtable/Telegram failures.
- Prompt-injection resistance is improved at the payload boundary and prompt layer, but no deterministic content scanner blocks unsafe drafts yet.
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
- WhatsApp webhook signature verification exists when `WHATSAPP_APP_SECRET` is configured.
- Manual `/approval/{lead_id}/approve` and `/reject` endpoints now require `WEBHOOK_SHARED_SECRET`, but they are still secondary legacy endpoints and can likely be removed once Telegram approval is the only owner approval path.
- Public POST endpoints now have basic in-process rate limiting and content-length limits. A production edge proxy should still enforce these outside Python too.
- No IP allowlist.
- WhatsApp and Telegram lead-message duplicate events are tracked in Postgres through `inbound_events`. This reduces duplicate processing from webhook retries, but is not a complete signed timestamp replay-defense system.
- Secrets live in `.env`; `.env` must never be committed.

### Reliability

- Stale `running` jobs are automatically recovered to `pending` after the configured threshold.
- Worker is a single process script, not a managed service.
- No dead-letter queue.
- Airtable and Telegram calls now use bounded retry/backoff for transient HTTP/network failures.
- Form jobs use lead duplicate checks. Messaging channels use conversation state plus inbound event IDs for webhook retry protection.
- Airtable failures can requeue jobs depending on where the failure happens.
- Telegram failures are returned after bounded retries; approval-required jobs now fail/requeue if the owner approval notification cannot be delivered.
- Worker logs are now compact summaries rather than full Telegram/WhatsApp payload dumps.

### Data correctness

- Airtable schema is assumed.
- Lead identity is `lead_id`; if Tally IDs change or field mappings shift, duplicates can happen.
- Inbound payloads are normalized, unknown Tally fields are ignored, and known fields are sanitized/length-limited. A stricter Pydantic validation layer is still pending.
- `urgency` normalization is currently limited to `same_day`, `this_week`, and `low`.
- Business configuration is still profile/prompt driven, not tenant-aware.
- Client onboarding/customization guidance is consolidated in `CLIENT_SETUP_CHECKLIST.md`.

### Agent behavior

- Supervisor still depends on prompt adherence for calling the correct subagents and saving artifacts.
- Decision normalizer makes send policy deterministic, but the draft content itself is still generated by the LLM.
- No automated content safety scanner exists before safe auto-send.
- No LLM eval suite exists yet for draft quality, hallucinated claims, or policy violations.
- Prompts now explicitly label lead/form text as untrusted customer input that must never override workflow, tools, approval, or policy.

### Deployment

- Local/ngrok setup only.
- No Dockerfile.
- No Railway/Render/Fly deployment configuration yet.
- No process manager configuration for API + worker.
- No production observability beyond LangSmith and local logs.

Deployment readiness is explicitly **out of scope for the current audit snapshot** and is the next planned implementation phase. The next phase should include:

- Deploy the FastAPI app and worker as separate processes.
- Use a production Postgres database.
- Move all secrets to managed environment variables.
- Confirm Tally, Telegram, and WhatsApp webhook URLs point to the deployed API URL, not ngrok.
- Configure health checks for the API process.
- Configure worker restart policy.
- Confirm Postgres checkpoint tables and app-owned queue/conversation tables are created in the production database.

### Operational Monitoring

Operational monitoring is explicitly **out of scope for the current audit snapshot** and is the second planned implementation phase after deployment readiness.

Current visibility:

- `GET /health`
- `GET /jobs`
- LangSmith traces
- Airtable `Leads` and `Agent_runs`
- Postgres `lead_jobs`, `channel_conversations`, `channel_messages`, `inbound_events`
- compact worker logs

Planned monitoring work:

- Expand `/health` to actively verify Postgres, Airtable, Telegram, WhatsApp, and model connectivity.
- Add `/jobs` filters for `failed`, `running`, `pending`, `waiting_approval`, and channel jobs.
- Add a protected failed-job retry endpoint.
- Add a protected conversation lookup endpoint for debugging channel state.
- Add basic metrics for queue age, first-response latency, owner-notification latency, and failure rate.
- Decide whether operational metrics live in Airtable, Postgres views, or a lightweight admin UI.

### Email

- Resend integration exists behind `EMAIL_TRANSPORT=resend`.
- Local/dev mode still defaults to simulated artifacts with `EMAIL_TRANSPORT=simulated`.
- No bounce/error handling.
- No unsubscribe/compliance layer.
- No domain authentication flow.

## What We Are About To Implement Next

Recommended next implementation order:

1. Deployment readiness:
   - Deploy API and worker as separate processes.
   - Use production Postgres.
   - Configure environment variables outside source control.
   - Confirm Tally, Telegram, and WhatsApp webhook URLs point to deployed URLs, not ngrok.
   - Add process restart policies for API and worker.

2. Operational monitoring:
   - Expand `/health` with active dependency checks.
   - Add `/jobs` filters for failed/running/pending/waiting jobs.
   - Add a protected failed-job retry endpoint.
   - Add conversation lookup/debug endpoints for support.
   - Add queue and first-response latency metrics.

3. Safer auto-send guard:
   - Add deterministic checks before `send_customer_email`.
   - Block auto-send if draft contains pricing, guarantees, discounts, legal claims, calendar commitments, or missing recipient email.

4. Airtable metrics dashboard:
   - Add deliberate Airtable fields for `queue_wait_seconds`, `owner_notification_seconds`, and `first_response_seconds`.
   - Write metrics to Airtable only after those fields exist so the API does not reject the whole update.

5. Auth hardening:
   - Remove legacy manual `/approval/{lead_id}/...` endpoints once Telegram approval is fully trusted.
   - Require shared secret for Tally webhook.
   - Confirm Telegram secret header is enforced in deployment.
   - Move rate limiting/request size protection to the deployment edge as well as the Python app.

6. Email deliverability hardening:
   - Add provider error classification and bounce handling.
   - Add unsubscribe/compliance policy before broad outbound use.
   - Keep `EMAIL_TRANSPORT=simulated` for local debugging.

7. Minimal evals:
   - Add tests for policy-violating drafts.
   - Add fixtures for hot lead, warm lead, bad fit, spam/vendor.
   - Assert expected send policy and final queue state.

8. Multi-client configuration:
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

I give this a status rating of: **87% production-shaped MVP after WhatsApp/Telegram messaging validation and v4 audit hardening**.

Meaning:

- It is now stronger than a local demo because it has real webhook intake, Airtable, Postgres queueing, Postgres checkpointing, Telegram owner approval, WhatsApp inbound/outbound messaging, Telegram inbound messaging, conversation state, duplicate webhook event protection, deterministic send policy, owner handoff controls, bounded LLM context for messaging conversations, optional Resend email transport, and compact operational logs.
- It is not yet a production deployment because deployment/process management is not finished, production monitoring is not built, email deliverability/compliance is not hardened, and deeper deterministic content-safety checks are still needed before fully trusting all auto-send paths.

What is YOUR rating compared to mine? Please give your percentage and explain the top 3 reasons your score differs.
