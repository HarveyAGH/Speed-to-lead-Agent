# Telegram Lead Channel

This adapter reuses the existing Telegram bot for inbound lead conversations. Owner approval callbacks still use the same `/telegram/webhook` route, but customer text messages now use the dedicated channel conversation workflow rather than the form/email workflow.

## Environment

No new credentials are required:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_OWNER_CHAT_ID=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_ALLOW_OWNER_AS_LEAD=false
```

`TELEGRAM_OWNER_CHAT_ID` is important because owner messages are ignored as lead intake. Non-owner private messages are treated as inbound leads.

For local testing with only one Telegram account, set `TELEGRAM_ALLOW_OWNER_AS_LEAD=true`. Keep it `false` in production so owner/admin messages do not accidentally become customer leads.

## Route

- `POST /telegram/webhook`

## Flow

1. Telegram sends all bot updates to `/telegram/webhook`.
2. If the update is a `callback_query`, `app.py` handles it as an owner approval/rejection.
3. If the update is a text message from a non-owner chat, `channels.telegram_leads.adapter` stores the message in `channel_conversations` / `channel_messages`.
4. `tools.channel_intake.ingest_channel_message()` queues a `job_type=channel_message` job.
5. `worker.py` routes that job to the dedicated speed-to-lead chat agent.
6. The chat agent sends a short channel-native reply back to the customer.
7. If the lead is qualified or needs human judgment, the owner receives a Telegram summary with extracted profile fields and recent transcript.
