# Agent Build Playbook

This is the repeatable pattern for building sellable LangGraph agents without getting lost in framework noise.

## Permanent Mental Model

```text
trigger
-> input data
-> deterministic tools
-> specialist subagents
-> explicit graph orchestration
-> visible artifacts
-> deterministic send policy
-> human approval only when risky
-> external action
```

If you can explain each box, you understand the system.

## Current Lead Intake System

```text
Tally form submission
-> FastAPI webhook
-> Airtable Leads row
-> Postgres lead_jobs queue
-> worker.py
-> explicit LangGraph StateGraph
-> lead qualifier / missing info / follow-up writer / CRM recorder
-> local artifacts + Airtable Agent_runs row
-> normalized send_policy
-> safe first responses auto-send from worker
-> risky responses interrupt() and request Telegram approval
-> graph resume after approval/rejection when needed
-> simulated sent-email artifact
```

## What Each Layer Owns

### Trigger

The trigger starts the workflow. Today this can be:

```text
manual LangGraph Studio prompt
or
POST /webhooks/tally
```

The trigger should not contain business reasoning. It only passes input into the system.

### Input Data

The data contract is the shape the agent expects:

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

If a new client uses different field names, map those names into this contract before the agent runs.

### Deterministic Tools

Tools do reliable actions:

```text
load_lead
save_run_artifacts
send_safe_followup_email
send_followup_email
send_owner_approval_request
```

Tools should not be mysterious. Each tool should read data, write data, or perform one external action.

CRM note writing is now owned by `save_run_artifacts`, so decision, draft, evidence, and `crm_note.md` land in one canonical run folder.

### Subagents

Subagents reason over the data:

```text
lead_qualifier_agent: decides fit, urgency, score
missing_info_detector_agent: finds missing fields/questions
followup_writer_agent: drafts the reply
crm_recorder_agent: summarizes for the owner/CRM
```

Each subagent gets a narrow job so the supervisor does not become one giant confused agent.

### Graph Orchestration

The graph owns the workflow order:

```text
load lead
run qualification
run missing info
draft follow-up
record CRM note
save artifacts
send automatically, request approval, or do not send based on send_policy
```

The graph is the map. Subagents are specialists. Tools are hands.

### Artifacts

Artifacts prove what happened:

```text
decision.json
draft_message.txt
evidence.json
crm_note.md
Airtable Agent_runs row
sent_email.json after approval
```

If a client asks, "What did the agent do?", artifacts answer that question.

### Human Approval

The approval boundary is where risk starts.

The agent can draft, log, and send safe clarification questions on its own.
It must pause before:

```text
customer-facing sends
pricing promises
discounts
contracts
refunds
anything legally sensitive
calendar or availability commitments
```

In this repo, the risk decision lives in `tools/decision_normalizer.py`.
The send execution is split:

```text
send_policy = auto_send
-> worker.py calls send_safe_followup_email directly
-> no interrupt

send_policy = approval_required
-> supervisor calls send_followup_email
-> interrupt()
-> Telegram Approve / Reject

send_policy = do_not_send
-> no customer-facing send
```

The owner approval surface is Telegram:

```text
Telegram message with classification, score, recommendation, and draft preview
-> Approve / Reject button
-> /telegram/webhook
-> Command(resume="approve" or "reject")
```

The owner should never approve blindly. The approval message must show enough
context to make a decision without opening LangSmith or Airtable:

```text
lead name
company
classification
fit
urgency
score
recommended action
draft subject
draft body preview
```

## Interview Whiteboard Version

Say this:

```text
I built a lead intake agent where a form or Airtable row provides the lead data.
The supervisor loads the lead, delegates qualification, missing-info detection,
follow-up drafting, and CRM-note creation to specialist subagents, then saves
evidence artifacts. The system writes the result to Airtable for visibility and
uses interrupt() before any customer-facing send. The owner receives a Telegram
approval message containing the decision snapshot and draft preview, and the
graph resumes only after the owner approves or rejects.
```

## Debugging Checklist

When something breaks, check in this order:

1. Did the trigger send the expected fields?
2. Did the lead get written to Airtable?
3. Did `load_lead` return `_source: "airtable"`?
4. Did each subagent receive populated JSON?
5. Did `save_run_artifacts` write local files?
6. Did Airtable `Agent_runs` receive a row?
7. Does `decision.json` include the expected `send_policy`?
8. If `auto_send`, did worker create `sent_email.json` and set the queue to `auto_sent`?
9. If `approval_required`, did `send_followup_email` interrupt before send?
10. Did Telegram send the owner an approval message?
11. Did the Telegram button hit `/telegram/webhook`?
12. Did approval create a `sent_email.json` artifact?

## What To Build Next

The next practical improvement is:

```text
add response-time metrics and stale-job recovery before replacing simulated
email sending with a real provider such as Resend
```
