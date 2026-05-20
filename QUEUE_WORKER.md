# Queue And Worker

This file explains the production queue in plain terms.

## The Problem

The old webhook did this:

```text
Tally submits form
-> FastAPI receives request
-> FastAPI runs the entire LangGraph workflow
-> FastAPI waits for LLM calls, Airtable writes, artifacts, and interrupt
-> FastAPI returns
```

That is risky because webhook requests should be short.

If the LLM takes 60 seconds, the HTTP request stays open for 60 seconds.
If the server restarts during that request, the work may be lost or unclear.
If many leads arrive together, the API server gets tied up doing slow agent work.

## The Production Pattern

The new flow is:

```text
Tally submits form
-> FastAPI saves the lead to Airtable
-> FastAPI creates a Postgres lead_jobs row
-> FastAPI immediately returns {"status": "queued"}
-> worker.py claims the queued job
-> worker.py runs the LangGraph workflow
-> worker.py sends Telegram approval request
```

FastAPI is now the receptionist.

The worker is now the person doing the actual back-office work.

Postgres is the job clipboard between them.

## What The Queue Stores

The queue table is called:

```text
lead_jobs
```

Important columns:

```text
id = unique job number
lead_id = which lead this job belongs to
payload = original normalized lead data
status = pending, running, waiting_approval, approved_sent, rejected_by_owner, succeeded, or failed
attempts = how many times the worker tried
max_attempts = retry limit
last_error = failure details if something broke
created_at = when job was created
started_at = when worker started it
finished_at = when worker completed it
```

## Why This Is More Production-Like

If FastAPI restarts:

```text
pending jobs remain in Postgres
```

If the worker reaches the approval boundary:

```text
the job becomes waiting_approval
```

If the owner taps Approve or Reject:

```text
the job becomes approved_sent or rejected_by_owner
```

If the worker crashes:

```text
the job status/error is visible in Postgres
```

If you want multiple workers later:

```text
FOR UPDATE SKIP LOCKED lets workers safely claim different jobs
```

## Commands

Start FastAPI:

```bash
cd /home/snowaflic/Multi-agents
. .venv/bin/activate
.venv/bin/uvicorn app:app --reload --port 8000
```

Start the worker:

```bash
cd /home/snowaflic/Multi-agents
. .venv/bin/activate
.venv/bin/python worker.py
```

Process one job and exit:

```bash
.venv/bin/python worker.py --once
```

List recent jobs:

```bash
.venv/bin/python worker.py --list
```

Inspect jobs directly in Postgres:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "SELECT id, lead_id, status, attempts, last_error FROM lead_jobs ORDER BY id DESC LIMIT 10;"
```
