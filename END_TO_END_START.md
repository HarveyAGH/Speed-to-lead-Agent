# End To End Start

Use this when the PC restarted and you need to bring the full lead intake agent back online.

The full system is:

```text
Postgres
-> FastAPI
-> ngrok
-> Telegram webhook
-> Tally webhook
-> Airtable
-> Postgres lead_jobs queue
-> Worker
-> LangGraph
-> LangSmith
```

## Terminal 1: Start Postgres

Open WSL Ubuntu terminal.

Run:

```bash
sudo service postgresql start
```

Verify Postgres works:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "SELECT version();"
```

Verify LangGraph checkpoint tables exist:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "\dt"
```

Expected tables:

```text
checkpoint_blobs
checkpoint_migrations
checkpoint_writes
checkpoints
```

Optional: check current checkpoint count before testing:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "SELECT COUNT(*) FROM checkpoints;"
```

## Terminal 2: Start FastAPI

Open a second WSL Ubuntu terminal.

Run:

```bash
cd /home/snowaflic/Multi-agents
. .venv/bin/activate
.venv/bin/uvicorn app:app --reload --port 8000
```

Leave this terminal running.

In another terminal, health check:

```bash
curl http://localhost:8000/health
```

Expected:

```json
{"ok":true,"airtable_configured":true,"queue_configured":true,"telegram_configured":true,"telegram_webhook_secret_configured":true}
```

## Terminal 3: Start Worker

Open a third WSL Ubuntu terminal.

Run:

```bash
cd /home/snowaflic/Multi-agents
. .venv/bin/activate
.venv/bin/python worker.py
```

Leave this terminal running.

The worker is the process that claims queued lead jobs and runs LangGraph.

If you only want to process one queued job and exit:

```bash
.venv/bin/python worker.py --once
```

To inspect recent queue jobs:

```bash
.venv/bin/python worker.py --list
```

## Terminal 4: Start ngrok

Open a fourth WSL Ubuntu terminal.

Run:

```bash
ngrok http 8000
```

Copy the forwarding URL:

```text
https://example.ngrok-free.dev
```

This URL changes on the free ngrok plan when you restart ngrok.

## Update `.env`

Open:

```text
/home/snowaflic/Multi-agents/.env
```

Update:

```bash
PUBLIC_BASE_URL=https://example.ngrok-free.dev
TELEGRAM_WEBHOOK_SECRET=use-a-random-secret-string
```

Use your actual ngrok forwarding URL.

After editing `.env`, restart FastAPI.

In Terminal 2:

```text
CTRL+C
```

Then run again:

```bash
cd /home/snowaflic/Multi-agents
. .venv/bin/activate
.venv/bin/uvicorn app:app --reload --port 8000
```

## Update Telegram Webhook

Run this in any WSL terminal:

```bash
cd /home/snowaflic/Multi-agents
set -a
source .env
set +a

curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=$PUBLIC_BASE_URL/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

Expected:

```json
{"ok":true,"result":true}
```

Verify Telegram webhook:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

Expected URL:

```text
https://your-ngrok-url/telegram/webhook
```

## Update Tally Webhook

Open Tally form settings.

Set the webhook URL to:

```text
https://your-ngrok-url/webhooks/tally
```

Use the same ngrok URL from `PUBLIC_BASE_URL`.

## End To End Test

Submit a new Tally form.

Watch Terminal 2 for:

```text
POST /webhooks/tally 200 OK
```

The webhook should return quickly with:

```json
{"status":"queued"}
```

Watch Terminal 3 for the worker processing output.

Watch Telegram for:

```text
Lead approval needed
Approve / Reject buttons
```

Before clicking Approve, restart FastAPI to prove Postgres persistence.

In Terminal 2:

```text
CTRL+C
```

Then:

```bash
.venv/bin/uvicorn app:app --reload --port 8000
```

Now click Approve in Telegram.

Watch Terminal 2 for:

```text
POST /telegram/webhook 200 OK
```

Check sent email artifact:

```bash
find /home/snowaflic/Multi-agents/outputs -name sent_email.json | sort
```

If `sent_email.json` appears after the restart, Postgres persistence is working.

## Check LangGraph Checkpoints

Check queue state:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "SELECT id, lead_id, status, attempts, last_error FROM lead_jobs ORDER BY id DESC LIMIT 10;"
```

Expected statuses:

```text
pending -> running -> waiting_approval -> approved_sent
pending -> running -> waiting_approval -> rejected_by_owner
```

Check checkpoint count:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "SELECT COUNT(*) FROM checkpoints;"
```

Inspect latest thread IDs:

```bash
psql "postgresql://langgraph:langgraph@localhost:5432/langgraph_checkpoints" -c "SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 10;"
```

Expected thread IDs look like:

```text
lead-lead_xxxxxxxx
```

## Common Fixes

If FastAPI says port 8000 is busy:

```bash
fuser -k 8000/tcp
```

Then restart:

```bash
.venv/bin/uvicorn app:app --reload --port 8000
```

If Telegram buttons do nothing:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

If Telegram says the webhook is set but FastAPI rejects callbacks, make sure:

```bash
echo "$TELEGRAM_WEBHOOK_SECRET"
```

matches the `secret_token` you used in `setWebhook`.

Check that the webhook URL matches your current ngrok URL.

If Tally submits but nothing reaches FastAPI:

```text
Check Tally webhook URL.
Check ngrok is still running.
Check FastAPI is still running.
```

If approval fails after restart:

```text
Check POSTGRES_DB_URI in .env.
Check Postgres is running.
Check graph.py is using PostgresSaver.
Check the same thread_id pattern is used in run and resume.
```

The required thread ID pattern is:

```python
f"lead-{lead_id}"
```
