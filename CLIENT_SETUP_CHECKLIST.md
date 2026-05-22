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

## 2. Choose Or Create The Niche Template

Start from:

```text
templates/_starter_template/
```

Copy it to a niche or client folder, then edit in this order:

```text
1. agency_profile.json
2. owner_configuration.json
3. test_scripts.md
```

After the niche/client files are complete, copy the JSON files into `mock_data/` for local testing:

```text
mock_data/agency_profile.json
mock_data/owner_configuration.json
```

Do not create one-off private client wording in the core repo unless this repo copy belongs only to that client.

## 3. Client Information To Collect

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

## 4. Main Files To Customize

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

#### Key-Level Customization Rules

Do not treat every JSON key the same way. Some keys are read by Python code, some are read only by the LLM, and some are legacy names that still need to stay stable until the code is changed.

Plain English:

```text
Changing a value usually changes behavior safely.
Renaming a key may silently disconnect that data from the code or prompt.
Removing a key is safe only when no code, prompt, Airtable field, or form mapping expects it.
```

##### `agency_name`

What it means:

```text
Legacy/internal label for "the business or offer this agent represents."
For an agency demo, this is the agency name.
For a clinic, law firm, roofing company, or locksmith, put the client's business name here.
```

Why the key still exists:

```text
The code and prompts already pass/read agency_profile.agency_name. Renaming the key to business_name without updating code can make the LLM lose the business identity.
```

Safe customization:

```json
"agency_name": "Clearview Dental"
```

If you want the key to be called `business_name` instead:

```text
1. Go to templates/_starter_template/agency_profile.json and add business_name.
2. Go to mock_data/agency_profile.json and add business_name.
3. Go to worker.py and update _channel_agency_profile_context() to read profile.get("business_name") or profile.get("agency_name").
4. Go to workflow_nodes.py and update any agency context helper to pass business_name.
5. Go to prompts/lead_qualifier.md, prompts/followup_writer.md, and prompts/speed_to_lead_chat.md if they mention agency_profile identity.
6. Run the full tests.
```

Recommended for now:

```text
Keep the key name agency_name. Put the client business name as the value.
```

##### `services`

What it does:

```text
The LLM reads this to understand what the business offers and whether the lead is asking for something relevant.
```

Safe customization:

```json
"services": [
  "Invisalign consultations",
  "dental implant consultations",
  "emergency dental appointments"
]
```

Do not remove this key unless:

```text
1. You replace it with another key such as service_lines.
2. You update prompts to tell the LLM to use service_lines.
3. You update worker.py / workflow_nodes.py context filtering helpers to pass service_lines.
```

##### `ideal_customer_profile`

What it does:

```text
The LLM reads this as the qualification rulebook. It decides fit, bad fit, urgency, and ROI fit from this section.
```

Safe customization:

```text
Change the values freely.
Keep the key unless you are also changing the prompts and context helpers.
```

Good keys inside it:

```text
business_type
buyer_types
monthly_ai_automation_budget_usd
min_monthly_revenue_for_automation
min_monthly_lead_volume_for_automation
preferred_timeline_for_automation
bad_fit_signals
```

Budget and timeline note:

```text
If a business does not want to ask budget/timeline early, do not necessarily remove every budget/timeline key from agency_profile. Instead, change the rule from "must ask immediately" to "use if disclosed; otherwise qualify from volume, urgency, and pain."
```

Example:

```json
"ideal_customer_profile": {
  "business_type": ["dental clinic", "orthodontic clinic"],
  "min_monthly_lead_volume_for_automation": 15,
  "budget_disclosure_policy": "Do not ask budget in the first message. If budget is not disclosed, qualify from lead volume, urgency, and pain severity.",
  "preferred_timeline_for_automation": "within 14 days",
  "bad_fit_signals": ["vendor pitch", "job seeker", "medical diagnosis request"]
}
```

If you remove budget as a qualification concept:

```text
1. Remove budget from required_fields_for_sales_call.
2. Remove or soften budget language in prompts/speed_to_lead_chat.md.
3. Remove or soften budget language in prompts/lead_qualifier.md only if form leads should stop using budget.
4. Update test scripts so medium/hot lead examples prove the new rule.
5. Run a hot, medium, and not-fit test.
```

##### `required_fields_for_sales_call`

What it does:

```text
The missing-info detector reads this for form leads.
The chat agent may also see it through compact channel profile context.
It tells the system what information is required before confidently booking/escalating.
```

If a client does not want to ask for budget:

```json
"required_fields_for_sales_call": [
  "service_interest",
  "timeline",
  "website"
]
```

If a client does not want to ask timeline:

```json
"required_fields_for_sales_call": [
  "service_interest",
  "budget",
  "website"
]
```

If the client runs a messaging-first workflow:

```text
Keep this short. Messaging should not feel like a form.
For chat, prefer asking one or two high-signal questions at a time.
```

If you rename a required field:

```text
1. Rename it in agency_profile.json.
2. If it comes from Tally, update app.py -> _normalize_field_name().
3. Add it to normalize_lead_payload if it is a new internal field.
4. Add the Airtable column if it should be stored.
5. Mention the new field in prompts/missing_info_detector.md if the LLM needs special reasoning.
```

##### `helpful_fields`, `urgent_lead_signals`, `qualification_rules`, `safety_rules`

What they do:

```text
These are LLM-readable business rules. Python code mostly just passes them through when present.
They are safe places to add niche-specific judgment without changing code.
```

Examples:

```json
"urgent_lead_signals": [
  "patient wants appointment this week",
  "high-value treatment interest",
  "lead says they are comparing providers now"
],
"qualification_rules": {
  "hot": "High-value treatment interest + near-term appointment need + reachable contact details.",
  "medium": "Real patient inquiry but missing urgency, location, or treatment interest.",
  "not_fit": "Vendor pitch, job seeker, medical emergency, or asks for diagnosis."
}
```

If these keys are ignored by a node:

```text
1. Check workflow_nodes.py context helpers for form workflow.
2. Check worker.py -> _channel_agency_profile_context() for messaging workflow.
3. Make sure the prompt tells the LLM to use those keys.
```

##### `owner` and `crm_statuses`

What they do:

```text
These are legacy/form-workflow support fields.
owner is weaker than owner_configuration.json and should not be the main owner source.
crm_statuses is mostly reference context.
```

Recommended:

```text
Do not customize owner here unless a specific prompt still depends on it.
Put owner identity in owner_configuration.json instead.
```

If token optimization removes these from LLM context, that is usually safe.

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

#### Owner Configuration Key Rules

This file is not the qualification brain. It is the identity and handoff config.

##### `owner_name`

What it does:

```text
Used in owner-facing alerts and customer handoff messages such as "Ahmed will follow up."
```

Customize the value:

```json
"owner_name": "Dr. Sarah Lee"
```

Do not rename the key unless you update:

```text
tools/owner_config.py
worker.py
tools/telegram.py
```

##### `business_name`

What it does:

```text
Used in customer-facing closing/handoff language and owner alerts.
For clinics, law firms, roofers, etc., this should be the client business name.
```

Customize:

```json
"business_name": "Clearview Dental"
```

##### `sender_name` and `sender_title`

What they do:

```text
Used mainly by the Tally/form email follow-up workflow.
Messaging channels usually speak as the business assistant and escalate to owner_name.
```

If the client does not want a named sender:

```text
Keep the keys, but use neutral values.
```

Example:

```json
"sender_name": "Clearview Dental Team",
"sender_title": "Patient Coordination Team"
```

If you remove these keys:

```text
1. Check workflow_nodes.py -> _owner_draft_context().
2. Check prompts/followup_writer.md.
3. Run one Tally/form lead test because email drafting depends on these fields.
```

##### `discovery_call_url`

What it does:

```text
Used by both form follow-up drafts and messaging handoff replies. If present, qualified leads may receive this booking link.
```

If the client does not want calendar links:

```json
"discovery_call_url": ""
```

Then verify:

```text
1. Messaging qualified handoff asks the lead to wait for the owner instead of booking.
2. Form follow-up asks for availability instead of inventing a link.
```

Do not delete the key unless you update:

```text
worker.py -> _discovery_call_url()
workflow_nodes.py -> _owner_draft_context()
prompts/followup_writer.md
prompts/speed_to_lead_chat.md
```

##### `timezone`

What it does:

```text
Mostly useful for scheduling language and future calendar integrations.
Current chat logic does not heavily depend on it.
```

Safe to keep. If unknown, use the client's local timezone or leave it blank.

##### `approval_channel`

What it does:

```text
Documentation/config intent for where owner approvals go. Current implementation is Telegram-based.
```

Do not assume changing this to `whatsapp` magically moves owner alerts. To change owner alert channels, update Telegram alert code and channel dispatch logic.

##### `approval_policy_note`

What it does:

```text
Human-readable policy note for owner behavior. It is useful documentation but should not be heavily passed into customer-facing chat context.
```

Safe customization:

```json
"approval_policy_note": "Escalate urgent patients, pricing questions, complaints, and uncertain medical language."
```

If it starts affecting model behavior, make sure the relevant prompt explicitly tells the LLM how to use it.

## 4A. If You Want To Rename Or Remove Keys

Use this checklist before changing JSON key names.

```text
1. Search the repo for the key name.
2. Decide whether the key is code-read or LLM-only.
3. If code-read, update Python helpers before renaming.
4. If LLM-only, update the prompt that explains the key.
5. If it comes from a form, update app.py field mapping.
6. If it is stored in Airtable, update Airtable columns and writeback code.
7. Add or update a test script proving the new behavior.
8. Run pytest.
9. Run one real smoke test through the affected channel.
```

Useful commands:

```bash
grep -RIn "agency_name" prompts agents tools workflow_nodes.py worker.py app.py
grep -RIn "required_fields_for_sales_call" prompts agents tools workflow_nodes.py worker.py app.py
grep -RIn "discovery_call_url" prompts agents tools workflow_nodes.py worker.py app.py
```

Example: remove budget from an early chat workflow without breaking the system:

```text
1. In agency_profile.json, remove "budget" from required_fields_for_sales_call.
2. Add a rule inside ideal_customer_profile:
   "budget_disclosure_policy": "Do not ask budget early. Qualify from lead volume, urgency, and pain. Ask budget only after fit is clear."
3. In prompts/speed_to_lead_chat.md, soften or remove any rule that forces budget early.
4. In test_scripts.md, create a hot lead that never discloses budget but has strong volume and urgency.
5. Run a WhatsApp/Telegram smoke test.
6. Confirm the AI does not force budget too early and still escalates strong leads.
```

Example: replace `timeline` with `appointment_urgency` for a clinic form:

```text
1. In Tally, change the label to "How soon do you want an appointment?"
2. In app.py -> _normalize_field_name(), map that label to "timeline" if you want to keep the existing internal field.
3. If you truly want a new field named appointment_urgency, add it to normalize_lead_payload and Airtable.
4. Add "appointment_urgency" to helpful_fields or required_fields_for_sales_call.
5. Update prompts/missing_info_detector.md if the missing-info agent should treat it specially.
6. Run one form smoke test and check Airtable + LangSmith.
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

## 5. Form Field Customization

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

## 6. Airtable Setup

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

## 7. Environment Variables

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

Email:

```bash
EMAIL_TRANSPORT=simulated
RESEND_API_KEY=
RESEND_FROM_EMAIL=
RESEND_REPLY_TO_EMAIL=
```

Use `EMAIL_TRANSPORT=simulated` for local demos and development. It writes `sent_email.json` artifacts and does not call a provider. Use `EMAIL_TRANSPORT=resend` only when the client is ready for real customer email, and set all Resend values before startup.

Webhook secret:

```bash
WEBHOOK_SHARED_SECRET=
ALLOW_INSECURE_LOCAL_WEBHOOKS=true
```

Production must set `WEBHOOK_SHARED_SECRET`. The local insecure flag is only for local development.

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

Temporary Meta access tokens are acceptable for local testing only. Production WhatsApp should use a long-lived System User token with the required WhatsApp permissions.

Public URL:

```bash
PUBLIC_BASE_URL=https://your-public-domain.example
```

Local testing can use ngrok. Production must use the deployed API URL.

## 8. Channel Setup

### Tally / Website Form

Webhook URL:

```text
{PUBLIC_BASE_URL}/webhooks/tally
```

If `WEBHOOK_SHARED_SECRET` is set, send it as:

```text
X-Webhook-Secret: <secret>
```

Tally/form leads run the form workflow and can produce email-style drafts. WhatsApp and Telegram messages run the live messaging workflow and should produce short chat-native replies.

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

## 9. When The AI Should Stop

The AI stops or avoids another LLM call when:

- owner is taking over
- owner marked lead booked
- owner marked lead not fit
- customer clearly closes the conversation
- lead was closed as not fit
- lead is already in owner handoff state

This protects tokens and prevents the bot from continuing after a human owns the conversation.

## 10. Test Checklist Before Showing A Client

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
1. Submit one Tally/form lead with EMAIL_TRANSPORT=simulated.
2. Approve a form workflow Telegram owner button when approval is required.
3. Send one low-fit vendor message.
4. Send one medium/not-ready real business message.
5. Send one high-fit urgent WhatsApp message.
6. Send one high-fit urgent Telegram lead message.
7. Click owner action in Telegram for a messaging escalation.
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

Inspection commands:

```bash
psql "$POSTGRES_DB_URI" -c "select id, lead_id, job_type, status, first_response, updated_at from lead_jobs order by updated_at desc limit 10;"
psql "$POSTGRES_DB_URI" -c "select conversation_id, channel, status, updated_at from channel_conversations order by updated_at desc limit 10;"
find outputs -name sent_email.json -print
find outputs -maxdepth 2 -type f -print | sort | tail -40
```

## 11. Industry Template Strategy

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

## 12. Client Handoff Checklist

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

## 13. Out Of Scope For This Phase

```text
production deployment
production monitoring
advanced analytics dashboard
full OAuth CRM integrations
```
