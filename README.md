# AI Lead Intake + Follow-Up Agent

A narrow LangGraph/LangChain MVP for agencies and small service businesses that lose revenue when inbound leads are not qualified, logged, and followed up quickly.

The current demo is intentionally focused:

```text
Tally form submission
-> ngrok public webhook
-> FastAPI
-> Airtable lead
-> Postgres lead_jobs queue
-> worker process
-> explicit LangGraph StateGraph pipeline
-> specialist subagents
-> LangSmith trace
-> local evidence artifacts
-> Airtable Agent_runs row
-> deterministic send policy
-> safe first response auto-send or Telegram owner approval
-> graph resume after approval when needed
-> simulated sent-email artifact
```

## Buyer

Small agencies, consultants, clinics, and local-service operators that receive inbound leads from forms, email, ads, or referrals and currently triage them manually.

## Problem

Inbound leads arrive with uneven detail. A human has to read the message, decide whether the lead is worth fast response, identify missing info, draft a reply, and save a CRM note. Slow or generic replies lose booked calls.

## What The Agent Does

For one inbound lead, the agent:

1. Loads the lead from Airtable, or mock JSON if Airtable is not configured.
2. Qualifies the lead and scores fit/urgency.
3. Detects missing required or helpful information.
4. Drafts a personalized customer-safe follow-up.
5. Saves a CRM-style internal note.
6. Saves decision, draft, and evidence artifacts under `outputs/<run_id>/`.
7. Writes the run result back to Airtable's `Agent_runs` table.
8. Normalizes the decision into a send policy.
9. Auto-sends low-risk clarification replies from the worker.
10. Pauses with LangGraph `interrupt()` before risky customer-facing sends.
11. Sends a Telegram approval request with the decision snapshot, owner summary, draft preview, and Approve / Reject buttons when approval is required.
12. Resumes the graph after the owner approves or rejects.

## Architecture

```text
lead_intake_agent
  graph.py
    load_lead
    qualify
    detect_missing
    draft_followup
    save_crm_note
    save_artifacts
    approval_gate
    send / do_not_send
    final_summary

  worker.py
    claims queued jobs
    sends owner notifications
    records final queue status
```

The workflow order is explicit in `graph.py`. Specialist LLM agents still perform judgment-heavy work, but the graph controls routing, artifacts, approval boundaries, and final status.

## Production-Shaped Flow

```text
Tally
-> FastAPI /webhooks/tally
-> Airtable Leads row
-> Postgres lead_jobs row
-> worker.py claims the pending job
-> LangGraph StateGraph with thread_id
-> specialist assessment and draft nodes
-> save artifacts + Agent_runs row
-> decision_normalizer derives send_policy
-> if auto_send: graph writes simulated sent_email.json
-> if approval_required: approval_gate calls interrupt()
-> Telegram approval message with decision snapshot and draft preview
-> /telegram/webhook receives button click
-> graph resumes with Command(resume="approve" or "reject")
-> simulated sent_email.json artifact
```

## Messaging Channel Flow

Telegram and WhatsApp are not treated as form submissions. They use a separate speed-to-lead conversation path:

```text
Telegram/WhatsApp message
-> channel adapter
-> channel_conversations + channel_messages tables
-> lead_jobs row with job_type=channel_message
-> worker.py claims the job
-> speed_to_lead_chat structured LLM agent
-> short chat-native customer reply
-> owner Telegram escalation if qualified or needs human judgment
```

The form workflow can draft email-style replies because the lead already submitted structured fields. The channel workflow does not require email and does not generate email subjects.

## What Is Real

- Airtable read is real when `AIRTABLE_API_KEY` and `AIRTABLE_BASE_ID` are configured.
- Airtable writeback to `Agent_runs` is real when Airtable is configured.
- The lead job queue is real Postgres via `lead_jobs`.
- The slow LLM workflow runs in `worker.py`, not inside the incoming webhook request.
- Local artifacts are real files under `outputs/`.
- Human approval is real via LangGraph `interrupt()` for risky sends.
- Safe first response auto-send is real in the worker, but still simulated by a local file write.
- Telegram approval buttons are real via Telegram Bot API.
- Telegram approval messages include the latest saved Airtable `Agent_runs` decision and draft.
- LangSmith tracing is real when LangSmith env vars are configured.
- Email sending is still simulated by writing `sent_email.json`; no real email is sent yet.
- Telegram and WhatsApp inbound messages are routed through a dedicated conversation workflow, not the form/email workflow.

## Setup

Create and install the environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Required model config:

```bash
AWS_BEARER_TOKEN_BEDROCK=
BEDROCK_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_REGION=us-east-1
```

Optional LangSmith tracing:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=lead-intake-followup-agent
```

Optional Telegram owner approval:

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_OWNER_CHAT_ID=
TELEGRAM_WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://your-ngrok-domain.example
```

## Airtable Setup

Create a base named:

```text
Lead Intake Agent Demo
```

Create two tables:

```text
Leads
Agent_runs
```

`Leads` fields:

```text
lead_id
received_at
name
email
company
role
source
service_interest
message
budget
timeline
website
status
```

`Agent_runs` fields:

```text
run_id
lead_id
classification
fit
urgency
score
recommended_next_action
draft_subject
draft_body
evidence_json
approval_status
artifact_paths
created_at
```

Set Airtable env vars:

```bash
AIRTABLE_API_KEY=your_personal_access_token
AIRTABLE_BASE_ID=your_base_id
AIRTABLE_LEADS_TABLE=Leads
AIRTABLE_AGENT_RUNS_TABLE=Agent_runs
```

Example `Leads` row:

```text
lead_id: lead_001
received_at: 2026-05-16T08:15:00+08:00
name: Maya Chen
email: maya@clearviewdental.example
company: Clearview Dental
role: Practice Manager
source: website_form
service_interest: paid search management and landing page optimization
message: We are opening a second clinic and need more implant consultation leads. We have tried Google Ads before but tracking was messy. Can we talk this week?
budget: $6000/month ad spend plus management fee
timeline: this month
website: https://clearviewdental.example
status: new
```

## Run

Start the FastAPI webhook server:

```bash
uvicorn app:app --reload --port 8000
```

Start the worker in a second terminal:

```bash
python worker.py
```

Expose it with ngrok:

```bash
ngrok http 8000
```

Set the Telegram callback webhook:

```bash
set -a
source .env
set +a

curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=$PUBLIC_BASE_URL/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

Optional: start LangGraph Studio for local graph debugging:

```bash
langgraph dev
```

Graph ID:

```text
lead_intake_agent
```

## Manual Demo Prompts

Draft-only run:

```text
Run the lead intake workflow for lead_001. Qualify it, find missing info, draft the reply, save the CRM note, save artifacts, and stop before sending unless I approve.
```

Expected result:

```text
load_lead returns _source: airtable
subagents run
artifacts are saved locally
Agent_runs gets a new Airtable row
no send interrupt occurs
```

Approval-gated send run:

```text
Run the lead intake workflow for lead_001. Qualify it, find missing info, draft the reply, save the CRM note, save artifacts, and then attempt to send the follow-up email through the approval-gated send tool.
```

Expected result:

```text
same workflow as above
send_followup_email pauses with interrupt()
human types approve
sent_email.json artifact is written
```

## Demo Script

1. Show the Tally lead form.
2. Submit a new lead.
3. Show ngrok/FastAPI receiving `POST /webhooks/tally`.
4. Show the new Airtable `Leads` row.
5. Show the new Airtable `Agent_runs` row.
6. Show LangSmith trace with tags/metadata for the lead.
7. Show Telegram approval message with decision snapshot, draft preview, and Approve / Reject buttons.
8. Tap Approve.
9. Show the approve trace in LangSmith.
10. Show `outputs/email_<lead_id>.../sent_email.json`.

## Human Boundary

The agent may:

```text
read lead data
classify and score leads
draft replies
save CRM notes
save evidence
write internal run artifacts
```

The agent must pause before:

```text
customer-facing send
pricing promises
discounts
contractual commitments
refunds or credits
```

## Webhook Test

The repo includes the end-to-end webhook path:

```text
POST /webhooks/tally
-> create Airtable Leads row
-> invoke the approval-gated agent workflow
-> write Agent_runs row
-> pause before send
-> send Telegram approval request with the saved draft preview
-> resume from Telegram button click
```

Run the API:

```bash
uvicorn app:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Test with a flat JSON payload:

```bash
curl -X POST http://localhost:8000/webhooks/tally \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Maya Chen",
    "email": "maya@clearviewdental.example",
    "company": "Clearview Dental",
    "role": "Practice Manager",
    "service_interest": "paid search management and landing page optimization",
    "message": "We are opening a second clinic and need more implant consultation leads. We have tried Google Ads before but tracking was messy. Can we talk this week?",
    "budget": "$6000/month ad spend plus management fee",
    "timeline": "this month",
    "website": "https://clearviewdental.example"
  }'
```

Optional webhook protection:

```bash
WEBHOOK_SHARED_SECRET=some-secret
```

When set, send this header:

```text
X-Webhook-Secret: some-secret
```

The API runs the approval-gated workflow. For local demos it uses `InMemorySaver`, so approval/resume works only while the same FastAPI process is still running. Production should replace this with SQLite or Postgres checkpointing.

## Learning Playbook

Read `AGENT_BUILD_PLAYBOOK.md` before modifying the architecture. It explains the permanent pattern:

```text
trigger -> input data -> tools -> subagents -> supervisor -> artifacts -> human approval -> external action
```

## Discovery Questions

- Where do new leads arrive today?
- How fast do you usually respond?
- What makes a lead qualified?
- What info must be present before you book a call?
- Where should qualified leads be saved?
- What would be unacceptable for the agent to send?
- Who approves outbound messages?
- What would make this worth paying for?
