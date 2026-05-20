# Simplified Repo Map

This file explains the codebase in plain English, ordered by the files that most directly affect how the agent behaves.

## 1. `mock_data/agency_profile.json`

This is the business brain.

It defines:

- what services the business offers
- who the ideal customer is
- what budget counts as qualified
- what fields are required before booking a call
- what makes a lead a bad fit

If the agent is qualifying leads incorrectly, check this file first.

Example:

```text
If this file says the agency sells paid search,
then a lead asking for AI automation may be rejected.
```

## 2. `prompts/*.md`

These files tell each agent how to think.

Important prompt files:

```text
prompts/lead_qualifier.md
prompts/missing_info_detector.md
prompts/followup_writer.md
prompts/crm_recorder.md
```

Simple meaning:

```text
agency_profile.json = what the business is
prompts/*.md = how each agent should reason
```

If the agent's judgment or tone is wrong, check the relevant prompt.

## 3. `graph.py`

This is the workflow map.

It defines the exact order:

```text
load lead
-> qualify lead
-> find missing info
-> draft reply
-> save CRM note
-> save artifacts
-> auto-send / approval gate / do not send
-> final summary
```

Simple meaning:

```text
graph.py = what happens first, second, third, and next?
```

## 4. `agents/*.py`

These files create the specialist subagents.

Each subagent has one focused job:

```text
agents/lead_qualifier.py = decides fit, urgency, score
agents/missing_info_detector.py = finds missing fields/questions
agents/followup_writer.py = writes the follow-up email
agents/crm_recorder.py = creates the internal CRM note
```

Simple meaning:

```text
agents/*.py = specialist LLM workers called by workflow_nodes.py
```

## 5. `tools/*.py`

Tools are what the system can actually do.

The LLM can reason, but tools perform real actions.

Important tool files:

```text
tools/lead_storage.py = loads leads from Airtable or mock data
tools/airtable_client.py = talks to Airtable API
tools/crm.py = saves CRM notes, artifacts, and Agent_runs rows
tools/decision_normalizer.py = turns messy agent decisions into stable fields and send policy
tools/email.py = handles approval-gated sends and safe simulated auto-sends
tools/telegram.py = formats and sends owner approval messages with draft previews and handles Telegram API calls
tools/job_queue.py = stores pending lead jobs in Postgres so work survives restarts
tools/io_helpers.py = shared file/output helpers
```

Simple meaning:

```text
tools/*.py = what the system can actually do
```

## 6. `app.py`

This is the external entry point.

It creates the FastAPI webhook so a real business event can trigger the agent.

Current path:

```text
POST /webhooks/tally
-> normalize lead payload
-> create Airtable Leads row
-> enqueue a Postgres lead_jobs row
-> return quickly to Tally
```

The webhook does not run the LLM directly anymore. It queues the job, then
`worker.py` does the slow agent work in the background.

## 6.5. `tools/decision_normalizer.py`

This is the safety brain for speed-to-lead.

The LLM can say messy things like:

```text
qualified high fit
book call
needs info
bad lead
```

The normalizer turns that into stable fields:

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

The important field is `send_policy`:

```text
auto_send = safe first response can be sent quickly
approval_required = owner must approve before send
do_not_send = no customer message should be sent
```

Simple meaning:

```text
tools/decision_normalizer.py = what is safe to send automatically?
```

Simple meaning:

```text
app.py = how outside business events enter the system
```

## 7. `worker.py`

This is the background processor.

It claims pending jobs from Postgres and runs the expensive LangGraph workflow.

Current path:

```text
worker.py
-> claim pending lead_jobs row
-> invoke explicit LangGraph StateGraph
-> pause before customer-facing send
-> read latest Agent_runs decision/draft
-> send Telegram approval request with draft preview
```

Simple meaning:

```text
worker.py = the process that does slow agent work outside the webhook request
```

## 8. `graph.py`

This exposes the LangGraph app.

LangGraph Studio reads this file to know what graph to run.

Simple meaning:

```text
graph.py = the graph entrypoint for LangGraph
```

## 9. `config.py`

This loads environment variables and shared settings.

It controls:

- Bedrock model ID
- AWS region
- output folder
- mock data folder
- prompt folder
- Airtable config
- webhook secret
- Telegram bot token
- Telegram owner chat ID
- Telegram webhook secret
- public base URL for callbacks
- Postgres database URI

Simple meaning:

```text
config.py = environment and settings
```

## 10. `.env`

This is your private local configuration.

It contains secrets and local settings.

Examples:

```text
AWS_BEARER_TOKEN_BEDROCK
BEDROCK_MODEL_ID
AIRTABLE_API_KEY
AIRTABLE_BASE_ID
WEBHOOK_SHARED_SECRET
TELEGRAM_BOT_TOKEN
TELEGRAM_OWNER_CHAT_ID
TELEGRAM_WEBHOOK_SECRET
PUBLIC_BASE_URL
POSTGRES_DB_URI
```

Do not commit this file.

Simple meaning:

```text
.env = private keys and local config
```

## 11. `.env.example`

This is the safe template version of `.env`.

It shows what environment variables are needed without exposing real secrets.

Simple meaning:

```text
.env.example = public setup template
```

## 12. `outputs/`

This is where the system saves proof of work.

Example outputs:

```text
decision.json
draft_message.txt
evidence.json
crm_note.md
sent_email.json
```

Simple meaning:

```text
outputs/ = visible artifacts proving what happened
```

## 13. `tests/`

This contains automated checks.

Current tests verify things like:

- mock lead loading
- Airtable fallback behavior
- webhook payload normalization

Simple meaning:

```text
tests/ = checks that important parts still work
```

## 14. `README.md`

This explains the project to another person.

It should answer:

- what the agent does
- who it is for
- how to run it
- how to demo it
- what is real vs simulated

## Key Approval Idea

Telegram does not make the qualification decision.

The supervisor and subagents make the decision first, then `save_run_artifacts`
writes that decision and draft into Airtable's `Agent_runs` table.

After that, `app.py` reads the latest `Agent_runs` row and asks
`tools/telegram.py` to format it into a clean owner approval message.

Simple meaning:

```text
supervisor/subagents = decide and draft
Airtable Agent_runs = saved source of truth
Telegram = owner review screen
```

Simple meaning:

```text
README.md = public project explanation
```

## 14. `AGENT_BUILD_PLAYBOOK.md`

This is the reusable mental model.

It explains the pattern you should use in future projects:

```text
trigger
-> input data
-> deterministic tools
-> specialist subagents
-> explicit graph orchestration
-> artifacts
-> human approval
-> external action
```

Simple meaning:

```text
AGENT_BUILD_PLAYBOOK.md = how to rebuild this architecture again
```

## Whole System In One View

```text
app.py
-> Airtable lead is created
-> graph.py exposes the LangGraph app
-> workflow_nodes.py runs each graph step
-> tools/lead_storage.py loads the lead
-> mock_data/agency_profile.json defines qualification rules
-> prompts/*.md guide agent reasoning
-> agents/*.py run specialist reasoning
-> tools/crm.py saves artifacts and Agent_runs
-> tools/email.py pauses before customer-facing send
-> tools/telegram.py sends approval buttons to the owner
-> app.py receives Telegram callback
-> graph resumes and writes sent_email.json
```

## Short Version

```text
agency_profile.json = what business are we?
prompts/*.md = how should each specialist think?
tools/*.py = what can the system actually do?
graph.py = who controls the workflow order?
app.py = how outside business events enter the system?
tools/telegram.py = how the owner approves/rejects from Telegram
outputs/ = proof that the system did the work
```
