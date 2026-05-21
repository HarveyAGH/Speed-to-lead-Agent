# Telegram Lead Channel

This adapter reuses the existing Telegram bot for inbound lead conversations. Owner approval callbacks still use the same `/telegram/webhook` route.

## Environment

No new credentials are required:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_OWNER_CHAT_ID=
TELEGRAM_WEBHOOK_SECRET=
```

`TELEGRAM_OWNER_CHAT_ID` is important because owner messages are ignored as lead intake. Non-owner private messages are treated as inbound leads.

## Route

- `POST /telegram/webhook`

## Flow

1. Telegram sends all bot updates to `/telegram/webhook`.
2. If the update is a `callback_query`, `app.py` handles it as an owner approval/rejection.
3. If the update is a text message from a non-owner chat, `channels.telegram_leads.adapter` turns it into a lead with:
   - `source = telegram`
   - `source_channel = telegram`
   - `channel_user_id = <sender chat id>`
4. `tools.lead_ingestion.ingest_lead()` writes the CRM lead and queues the job.
5. The worker processes the job.
6. If policy allows auto-send, `channels.channel_dispatcher` sends the drafted reply back to the lead's Telegram chat.
7. If approval is required, the owner approves in Telegram and the approved draft is sent back to the lead's Telegram chat.
