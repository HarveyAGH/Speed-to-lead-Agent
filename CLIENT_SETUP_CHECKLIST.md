# Client Setup Checklist

This is the source of truth for onboarding a new client onto this speed-to-lead system.

Use this when preparing a client-specific version of the repo, configuring a demo, or turning an industry template into a paid implementation.

## 1. What This System Does For A Client

The system watches inbound lead channels, responds quickly, qualifies the lead, writes the lead to Airtable, and alerts the business owner when a human should take over.

Supported intake paths:

```text
Tally / website form
-> FastAPI
-> Airtable lead row
-> Postgres queue
-> worker
-> LangGraph form workflow
-> Airtable Agent_runs row
-> safe auto-send or Telegram owner approval
```

```text
Telegram / WhatsApp message
-> channel webhook
-> Postgres conversation tables
-> Postgres queue
-> worker
-> speed-to-lead chat agent
-> customer reply
-> Airtable messaging lead snapshot
-> Telegram owner escalation if qualified
```

Plain English:

```text
Forms are structured intake.
Messaging channels are live conversations.
Do not treat messaging leads like email drafts.
```

## 2. Client Information To Collect

Collect this before changing code.

Business identity:

```text
Business name:
Owner name:
Owner title:
Sender name:
Sender title:
Timezone:
Calendar / booking link:
```

Business rules:

```text
Business type:
Services sold:
Best-fit customer types:
Bad-fit lead signals:
Minimum budget or volume threshold:
Urgent lead signals:
Sensitive topics to avoid:
```

Lead channels:

```text
Website form / Tally:
Telegram:
WhatsApp:
Other:
```

Owner approval preferences:

```text
Who receives owner alerts?
Should safe first responses auto-send?
Which messages always require owner approval?
When should the AI stop talking?
When should a calendar link be sent?
```

## 3. Main Files To Customize

### `mock_data/agency_profile.json`

This is the business brain.

Customize it for:

- services offered
- ideal customer profile
- bad-fit signals
- required fields
- helpful fields
- budget thresholds
- timeline thresholds
- qualification rules

Example for a dentistry client:

```json
{
  "agency_name": "Clearview Dental",
  "services": [
    "Invisalign consultations",
    "dental implants",
    "emergency dental appointments"
  ],
  "ideal_customer_profile": {
    "business_type": ["dental clinic", "orthodontic clinic"],
    "monthly_ai_automation_budget_usd": 1000,
    "preferred_timeline_for_automation": "within 5 days",
    "bad_fit_signals": [
      "vendor pitch",
      "job seeker",
      "medical diagnosis request",
      "asks for guaranteed medical result"
    ]
  },
  "required_fields_for_sales_call": [
    "service_interest",
    "timeline"
  ],
  "helpful_fields": [
    "treatment_interest",
    "preferred_location",
    "insurance_status",
    "appointment_urgency"
  ]
}
```

Rule:

```text
If the agent is judging whether someone is a good lead, the logic belongs here.
```

### `mock_data/owner_configuration.json`

This controls owner-facing identity and handoff behavior.

Customize it for:

- owner name
- business name
- sender identity
- calendar link
- timezone
- approval policy note

Example:

```json
{
  "owner_name": "Dr. Sarah Lee",
  "business_name": "Clearview Dental",
  "sender_name": "Sarah Lee",
  "sender_title": "Clinic Director",
  "discovery_call_url": "https://cal.com/clearview/consult",
  "timezone": "Asia/Manila",
  "approval_channel": "telegram",
  "approval_policy_note": "Escalate pricing, medical promises, uncertain leads, or urgent patient requests to the owner."
}
```

Rule:

```text
If it changes who the owner is or how handoff looks, it belongs here.
```

### `prompts/speed_to_lead_chat.md`

This controls live Telegram/WhatsApp conversation behavior.

Customize it only when the industry needs different safety/tone rules.

Examples:

```text
Dentistry:
- never diagnose
- never promise treatment outcomes
- ask treatment interest and preferred appointment timing

Law:
- never give legal advice
- ask case type, jurisdiction, urgency, and incident date

Roofing:
- ask issue type, property type, location, active leak, storm damage
- never promise exact pricing before inspection

Locksmith:
- ask location, lockout/rekey/commercial type, urgency
- never promise exact arrival time unless configured
```

Rule:

```text
Do not put one client's private details in this prompt unless this repo copy belongs only to that client.
```

### Form Workflow Prompts

These are used by the Tally/form workflow:

```text
prompts/lead_qualifier.md
prompts/missing_info_detector.md
prompts/followup_writer.md
prompts/crm_recorder.md
```

Customize these when form leads need industry-specific reasoning.

The live chat workflow does not use these prompts for customer conversation.

## 4. Form Field Customization

The form field contract is in:

```text
app.py
```

Function:

```python
def _normalize_field_name(name: Any) -> str:
```

This maps Tally labels into internal field names.

Existing internal fields:

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

If a client changes the form label but wants the same internal meaning, update `_normalize_field_name`.

Example:

```python
"what treatment are you interested in": "service_interest",
"preferred appointment timeline": "timeline",
```

If a client adds a brand-new internal field:

1. Add the Tally field.
2. Add the label mapping in `_normalize_field_name`.
3. Add the field in `normalize_lead_payload`.
4. Add the field to Airtable if it should be stored there.
5. Add it to `agency_profile.json` if the LLM should care.
6. Update prompts only if the field requires special reasoning.

Safer budget removal rule:

```text
If the client does not want Budget on the form, remove it from the form and from agency_profile required fields.
Leave the code field as an empty optional value unless every budget reference has been audited.
```

## 5. Airtable Setup

Create or confirm two tables:

```text
Leads
Agent_runs
```

Required `Leads` fields:

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

Required `Agent_runs` fields:

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

Messaging leads are written into `Leads` with statuses such as:

```text
messaging_active
qualified_messaging_lead
messaging_not_fit
messaging_customer_closed
messaging_needs_human
owner_taking_over
owner_marked_booked
owner_marked_not_fit
```

## 6. Environment Variables

Start from `.env.example`.

Core model:

```bash
AWS_BEARER_TOKEN_BEDROCK=
BEDROCK_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_REGION=us-east-1
```

Postgres:

```bash
POSTGRES_DB_URI=postgresql://user:password@host:5432/dbname
```

Airtable:

```bash
AIRTABLE_API_KEY=
AIRTABLE_BASE_ID=
AIRTABLE_LEADS_TABLE=Leads
AIRTABLE_AGENT_RUNS_TABLE=Agent_runs
```

Telegram owner alerts:

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_OWNER_CHAT_ID=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_ALLOW_OWNER_AS_LEAD=false
```

WhatsApp:

```bash
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
```

Public URL:

```bash
PUBLIC_BASE_URL=https://your-public-domain.example
```

Local testing can use ngrok. Production must use the deployed API URL.

## 7. Channel Setup

### Tally / Website Form

Webhook URL:

```text
{PUBLIC_BASE_URL}/webhooks/tally
```

If `WEBHOOK_SHARED_SECRET` is set, send it as:

```text
X-Webhook-Secret: <secret>
```

### Telegram Owner Approval

Set webhook:

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=$PUBLIC_BASE_URL/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

### WhatsApp

Meta webhook callback URL:

```text
{PUBLIC_BASE_URL}/whatsapp/webhook
```

Verify token:

```text
WHATSAPP_VERIFY_TOKEN
```

Webhook event subscription:

```text
messages
```

## 8. When The AI Should Stop

The AI stops or avoids another LLM call when:

- owner is taking over
- owner marked lead booked
- owner marked lead not fit
- customer clearly closes the conversation
- lead was closed as not fit
- lead is already in owner handoff state

This protects tokens and prevents the bot from continuing after a human owns the conversation.

## 9. Test Checklist Before Showing A Client

Run tests:

```bash
.venv/bin/python -m pytest
```

Start services:

```bash
.venv/bin/uvicorn app:app --reload --port 8000
```

```bash
.venv/bin/python worker.py
```

Verify health:

```bash
curl http://localhost:8000/health
```

Test paths:

```text
1. Submit one Tally/form lead.
2. Send one low-fit vendor message.
3. Send one medium/not-ready real business message.
4. Send one high-fit urgent WhatsApp message.
5. Click owner action in Telegram.
```

Confirm:

```text
Airtable Leads row exists.
Airtable Agent_runs row exists for form workflow.
Postgres lead_jobs status is final.
Postgres channel_conversations status is correct.
Telegram owner alert looks readable.
WhatsApp/Telegram customer response is short and chat-native.
LangSmith trace appears.
Worker logs are compact.
Duplicate WhatsApp/Telegram events do not create duplicate jobs.
```

## 10. Industry Template Strategy

Keep one clean core repo, then create client-ready templates from it.

Template examples:

```text
speed-to-lead-dentistry
speed-to-lead-law-firms
speed-to-lead-roofing
speed-to-lead-locksmiths
speed-to-lead-medspas
speed-to-lead-real-estate
```

Each template should keep the same architecture but customize:

```text
mock_data/agency_profile.json
mock_data/owner_configuration.json
prompts/speed_to_lead_chat.md
prompts/lead_qualifier.md
prompts/missing_info_detector.md
prompts/followup_writer.md
```

Only customize code when the intake contract changes:

```text
app.py
channels/telegram_leads/adapter.py
channels/whatsapp/adapter.py
```

Rule:

```text
Reusable industry logic belongs in a template.
One-off client wording belongs in that client's repo/config.
Do not pollute the core repo with one client's private workflow unless it is reusable.
```

## 11. Client Handoff Checklist

Before calling the client implementation ready:

```text
[ ] Owner config has real owner name, business name, timezone, and calendar link.
[ ] Agency profile reflects real services and bad-fit signals.
[ ] Tally/form fields match app.py mappings.
[ ] Airtable tables have required columns.
[ ] Telegram owner bot receives alerts.
[ ] WhatsApp webhook is verified.
[ ] Low, medium, and high lead paths were tested.
[ ] Owner takeover stops AI replies.
[ ] Calendar link appears only for qualified/high-potential leads.
[ ] Airtable shows messaging leads clearly.
[ ] Worker logs are compact.
[ ] LangSmith traces are visible.
[ ] No real email provider is enabled unless intentionally configured.
```

