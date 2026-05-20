# The SQL Production Setup

This file explains the exact Postgres setup used to make LangGraph human approval survive a server restart.

The goal is not to become a database expert. The goal is to understand enough to know what the database is doing for this agent.

## Why We Need Postgres

The agent uses LangGraph `interrupt()` before sending a customer-facing email.

That creates this flow:

```text
lead arrives
-> agent qualifies lead
-> agent drafts email
-> agent pauses before sending
-> owner approves later
-> graph resumes and sends/simulates email
```

For that pause/resume to survive a server restart, LangGraph needs to save the graph state somewhere durable.

`InMemorySaver` saves state only inside the running Python process.

```text
server restarts
-> memory disappears
-> approval cannot resume
```

`PostgresSaver` saves state inside Postgres.

```text
server restarts
-> checkpoint still exists in Postgres
-> approval can resume using the same thread_id
```

## What Postgres Is In This Project

Postgres is the durable storage layer for LangGraph checkpoints.

It is not replacing Airtable.

Current responsibilities:

```text
Airtable = business data and owner-visible run records
Postgres = hidden LangGraph checkpoint state for resume/retry
outputs/ = local demo artifacts
LangSmith = trace visibility
```

## Step 1: Install Postgres In WSL

Run this in the WSL Ubuntu terminal:

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
```

What this does:

```text
postgresql = the actual database server
postgresql-contrib = useful extra Postgres tools/extensions
```

## Step 2: Start Postgres

Run:

```bash
sudo service postgresql start
```

Check status:

```bash
sudo service postgresql status
```

Expected meaning:

```text
active = Postgres service is available
```

Note: On Ubuntu, the status can show `active (exited)` for the parent service while the real database cluster still runs underneath. The real proof is whether `psql` can connect.

## Step 3: Create A Database User

Run:

```bash
sudo -u postgres psql -c "CREATE USER langgraph WITH PASSWORD 'langgraph';"
```

What this means:

```text
sudo -u postgres = run this command as the built-in Postgres admin user
psql = Postgres command-line client
-c = run this SQL command and exit
CREATE USER langgraph = create a database login named langgraph
WITH PASSWORD 'langgraph' = set its password
```

Why we do this:

```text
Our Python app should not connect as the root Postgres admin user.
It gets its own database user.
```

## Step 4: Create The Checkpoint Database

Run:

```bash
sudo -u postgres psql -c "CREATE DATABASE langgraph_checkpoints OWNER langgraph;"
```

What this means:

```text
CREATE DATABASE langgraph_checkpoints = create a database for LangGraph checkpoint tables
OWNER langgraph = let the langgraph user own it
```

Why we do this:

```text
LangGraph needs somewhere to create its checkpoint tables.
This database is dedicated to that purpose.
```

## Step 5: Grant Privileges

Run:

```bash
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE langgraph_checkpoints TO langgraph;"
```

What this means:

```text
GRANT ALL PRIVILEGES = allow the langgraph user to use the database fully
ON DATABASE langgraph_checkpoints = target this database
TO langgraph = give those permissions to the langgraph user
```

Why we do this:

```text
The Python app needs permission to create/read/write checkpoint tables.
```

## Step 6: Test The Connection

Run:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "SELECT version();"
```

What this means:

```text
psql = connect to Postgres
postgresql://... = connection URI
-c "SELECT version();" = run a simple query and exit
```

Breakdown of the URI:

```text
postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints
             |         |         |         |    |
             user      password  host      port database
```

Expected output:

```text
PostgreSQL 16.x ...
```

If this works, Python can connect too.

## Step 7: Add The URI To `.env`

Add:

```bash
POSTGRES_DB_URI=postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints?sslmode=disable
```

What this means:

```text
POSTGRES_DB_URI = environment variable the app reads
sslmode=disable = local dev connection does not use SSL
```

Why `.env`:

```text
The database connection string is config, not code.
Different environments can use different databases without changing graph.py.
```

## Step 8: Install Python Packages

Run inside the repo virtual environment:

```bash
cd /home/snowaflic/Multi-agents
. .venv/bin/activate
pip install langgraph-checkpoint-postgres "psycopg[binary]"
```

What these packages do:

```text
langgraph-checkpoint-postgres = LangGraph Postgres checkpointer
psycopg[binary] = Python driver that talks to Postgres
```

Without these, Python cannot import:

```python
from langgraph.checkpoint.postgres import PostgresSaver
```

## Step 9: Verify Python Can Read The URI

Run:

```bash
python - <<'PY'
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(dotenv_path=Path(".env"))
print(os.getenv("POSTGRES_DB_URI"))
PY
```

Expected output:

```text
postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints?sslmode=disable
```

Why this matters:

```text
If Python cannot read the URI, graph.py cannot create PostgresSaver.
```

## Step 10: Verify PostgresSaver Imports

Run:

```bash
python - <<'PY'
from langgraph.checkpoint.postgres import PostgresSaver
print(PostgresSaver)
PY
```

Expected output:

```text
<class 'langgraph.checkpoint.postgres.PostgresSaver'>
```

Why this matters:

```text
This proves the LangGraph Postgres package is installed correctly.
```

## Step 11: Replace InMemorySaver In `graph.py`

Current demo-only behavior:

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
```

Production-shaped behavior:

```python
from langgraph.checkpoint.postgres import PostgresSaver
```

The app should:

```text
1. Read POSTGRES_DB_URI from .env
2. Create a PostgresSaver
3. Run checkpointer.setup()
4. Compile the graph with that checkpointer
5. Reuse the same thread_id when resuming
```

The thread ID is critical.

Example:

```python
"thread_id": f"lead-{lead_id}"
```

If the original run uses:

```text
thread_id = lead-lead_123
```

Then the approval resume must use:

```text
thread_id = lead-lead_123
```

That is how LangGraph finds the saved checkpoint.

## Step 12: Check That LangGraph Created Tables

After wiring `PostgresSaver` and running the app once, run:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "\dt"
```

What this does:

```text
\dt = show tables
```

Expected result:

```text
LangGraph checkpoint tables should appear.
```

If no tables appear:

```text
The graph probably has not run with PostgresSaver yet,
or checkpointer.setup() was not called.
```

## Local Demo vs Production

### InMemorySaver

Good for:

```text
quick local demo
LangGraph Studio experiments
learning interrupt/resume
```

Bad for:

```text
server restarts
real customers
long-running approval flows
```

### PostgresSaver

Good for:

```text
approval links/buttons
server restarts
real persistence
production-like demos
```

Requires:

```text
running Postgres database
POSTGRES_DB_URI
langgraph-checkpoint-postgres package
same thread_id during resume
```

## Mental Model

Postgres does not run the agent.

Postgres remembers where the agent paused.

LangGraph does the orchestration.

FastAPI receives external events.

Telegram gets the owner decision.

Postgres lets the graph continue even if the server restarted between those steps.

## Current Project Target

The target architecture is:

```text
Tally webhook
-> FastAPI
-> Airtable lead row
-> LangGraph StateGraph pipeline
-> Postgres checkpoint saved during interrupt
-> Telegram approval button
-> FastAPI receives Telegram callback
-> LangGraph resumes from Postgres using same thread_id
-> simulated or real email send
```

That is the reason we installed Postgres.
