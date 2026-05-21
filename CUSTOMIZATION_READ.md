# Customization Read

This file explains how to customize the system for a new client or business type without getting lost.

The important mental model:

```text
Business profile = how the agent judges leads
Owner configuration = who owns the workflow and how owner-facing messages look
Form contract = what fields enter the system
Prompts = how each specialist reasons
Graph = the fixed workflow order
Tools = the real reads/writes/actions
```

## 1. The Main Client Customization File

Customize this file first:

```text
mock_data/agency_profile.json
```

This is the business brain.

It should describe the client's actual business:

- business name
- business type
- services offered
- ideal customer profile
- bad-fit signals
- required fields
- helpful fields
- minimum budget or qualification threshold
- common lead situations
- tone / positioning

Example for a clinic:

```json
{
  "agency_name": "Clearview Dental",
  "business_type": "dental clinic",
  "services": [
    "dental implants",
    "cosmetic dentistry",
    "emergency dental care"
  ],
  "ideal_customers": [
    "patients asking about dental implants",
    "patients needing urgent dental appointments",
    "patients asking about cosmetic consultations"
  ],
  "bad_fit_signals": [
    "vendor outreach",
    "job applications",
    "marketing spam"
  ],
  "required_fields_for_sales_call": [
    "service_interest",
    "message",
    "timeline"
  ],
  "helpful_fields": [
    "preferred_location",
    "preferred_appointment_time",
    "insurance_status"
  ]
}
```

Plain English:

```text
agency_profile.json tells the LLM what kind of business this is and what a good lead looks like.
```

## 2. How The Business Profile Reaches The Agents

The business profile is loaded through:

```text
tools/lead_storage.py
```

Function:

```python
@tool("get_agency_profile")
def get_agency_profile() -> str:
    return json.dumps(_read_json(MOCK_DATA_DIR / "agency_profile.json"), indent=2)
```

The graph loads this profile once in `load_lead_node`, then passes it inside the runtime context to each specialist agent.

The specialist agents are created in:

```text
agents/lead_qualifier.py
agents/missing_info_detector.py
agents/followup_writer.py
agents/crm_recorder.py
```

They are imported and invoked inside:

```text
workflow_nodes.py
```

Important lines conceptually:

```python
lead_qualifier_agent = build_lead_qualifier(MODEL)
missing_info_detector_agent = build_missing_info_detector(MODEL)
followup_writer_agent = build_followup_writer(MODEL)
crm_recorder_agent = build_crm_recorder(MODEL)
```

Then each graph node calls the relevant specialist:

```text
qualify_node -> lead_qualifier_agent
detect_missing_node -> missing_info_detector_agent
draft_followup_node -> followup_writer_agent
save_crm_note_node -> crm_recorder_agent
```

Full path:

```text
agency_profile.json
-> get_agency_profile loaded by load_lead_node
-> agency_profile added to graph state
-> workflow_nodes.py passes agency_profile into each specialist runtime prompt
-> specialist agent prompt
-> graph.py workflow
```

## 3. How The Graph Connects Everything

The graph is defined in:

```text
graph.py
```

Current workflow:

```text
START
-> load_lead
-> qualify
-> detect_missing
-> draft_followup
-> save_crm_note
-> save_artifacts
-> route by send_policy
   -> approval_gate
   -> send
   -> do_not_send
-> final_summary
-> END
```

Plain English:

```text
graph.py controls the workflow order.
workflow_nodes.py contains the actual Python functions for each step.
agents/*.py create specialist LLM workers.
tools/*.py read/write external systems.
```

## 4. Owner Configuration

Customize this file for owner-facing messages:

```text
mock_data/owner_configuration.json
```

Example:

```json
{
  "owner_name": "Dr. Sarah Lee",
  "business_name": "Clearview Dental",
  "sender_name": "Sarah Lee",
  "sender_title": "Clinic Director",
  "timezone": "Asia/Manila",
  "approval_channel": "telegram",
  "approval_policy_note": "Auto-send safe first responses only. Ask the owner before pricing promises, discounts, legal commitments, or uncertain cases."
}
```

This file connects through:

```text
config.py
-> tools/owner_config.py
-> tools/telegram.py
-> Telegram owner messages
```

Use this for:

- owner name
- business name
- sender name
- sender title
- timezone
- approval policy wording

Do not use this for qualification rules. Qualification rules belong in `agency_profile.json`.

## 5. Form Fields

The form field mapping is in:

```text
app.py
```

Function:

```python
def _normalize_field_name(name: Any) -> str:
```

This maps Tally labels into internal field names.

Example:

```python
"email address": "email",
"service interest": "service_interest",
"timeline": "timeline",
```

If a clinic form uses:

```text
What treatment are you interested in?
```

Add:

```python
"what treatment are you interested in": "service_interest",
```

If the form uses:

```text
Preferred appointment timeline
```

Add:

```python
"preferred appointment timeline": "timeline",
```

## 6. Adding A New Field

Example new field:

```text
Preferred clinic location
```

Step 1: Add it to the Tally form.

Step 2: Add label mapping in `app.py`:

```python
"preferred clinic location": "preferred_location",
```

Step 3: Add it to the normalized lead payload in `app.py`:

```python
"preferred_location": _sanitize_lead_value(fields.get("preferred_location"), limit=200),
```

Step 4: Add it to `agency_profile.json` if the LLM should care:

```json
{
  "helpful_fields": [
    "preferred_location"
  ]
}
```

Step 5: Edit prompts only if the field needs special reasoning.

Relevant prompts:

```text
prompts/lead_qualifier.md
prompts/missing_info_detector.md
prompts/followup_writer.md
prompts/crm_recorder.md
```

## 7. Removing Budget

Do not rush to delete the `budget` key from code.

Safer path:

```text
1. Remove Budget from the Tally form.
2. Remove budget as a required field from agency_profile.json.
3. Leave app.py's budget field in place.
```

Why?

If the form stops sending budget, `app.py` will keep:

```python
"budget": ""
```

That is usually safer than deleting the key because prompts/tools may still expect the field to exist.

Only remove it from code after checking every place that reads:

```text
budget
```

## 8. Prompt Customization

Use prompts when the agent's reasoning or tone needs to change.

Files:

```text
prompts/lead_qualifier.md
prompts/missing_info_detector.md
prompts/followup_writer.md
prompts/crm_recorder.md
```

Examples:

```text
For a clinic:
- be careful with medical claims
- never diagnose
- invite appointment scheduling
- ask insurance/location/treatment questions only when useful

For a law firm:
- never give legal advice
- ask for case type, urgency, jurisdiction
- route urgent matters to human review

For home services:
- ask location, job type, urgency, property type
- flag emergency jobs quickly
```

## 9. Where The LLM Actually Is

The LLM is not in the webhook.

The path is:

```text
Tally
-> app.py receives webhook
-> app.py saves lead and queues job
-> worker.py claims job
-> graph.py starts StateGraph
-> workflow_nodes.py invokes specialist agents
-> specialist agents call MODEL from config.py
```

`config.py` creates the model:

```python
llm = ChatBedrock(...)
MODEL = llm
```

Then `workflow_nodes.py` passes `MODEL` into each specialist agent builder.

## 10. Speed-To-Lead Policy

The product should not blindly send risky messages.

The practical production policy:

```text
Safe instant first response: can auto-send.
Sales commitment / pricing / discount / uncertain case: owner approval.
```

Safe auto-send means:

- acknowledge the inquiry
- personalize based on what they asked
- ask 1-3 clarifying questions
- avoid pricing promises
- avoid guarantees
- avoid legal/medical/financial advice
- avoid discounts
- avoid committing the owner to a specific offer

Owner approval means:

- the message includes pricing
- the message includes a strong sales promise
- the lead is high value
- the lead is sensitive
- the agent is uncertain
- the client wants strict control

## 11. The Customization Checklist

For each new client:

```text
1. Edit agency_profile.json.
2. Edit owner_configuration.json.
3. Customize Tally form fields.
4. Update app.py _normalize_field_name if labels changed.
5. Update app.py normalize_lead_payload only if adding new internal fields.
6. Update prompts only if the business logic/tone changed.
7. Run tests.
8. Submit one test form.
9. Check Airtable.
10. Check Telegram.
11. Check LangSmith trace.
12. Check Postgres lead_jobs status.
```

That is the customization path.
