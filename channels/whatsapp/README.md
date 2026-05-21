# WhatsApp Channel

This adapter receives WhatsApp Cloud API webhook messages and routes inbound text into the dedicated channel conversation workflow. WhatsApp is treated as a live conversation channel, not as a form submission.

## Environment

Add these values to `.env`:

```env
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
```

`WHATSAPP_VERIFY_TOKEN` is any secret string you choose and paste into Meta's webhook setup. `WHATSAPP_APP_SECRET` is used to verify signed webhook POST requests.

## Routes

- `GET /whatsapp/webhook`: Meta webhook verification.
- `POST /whatsapp/webhook`: inbound WhatsApp message intake.

## Flow

1. Meta sends the inbound message to `POST /whatsapp/webhook`.
2. `channels.whatsapp.adapter` extracts the phone number and text.
3. `tools.channel_intake.ingest_channel_message()` stores the message in `channel_conversations` / `channel_messages`.
4. The same function queues a `job_type=channel_message` job.
5. `worker.py` routes that job to the dedicated speed-to-lead chat agent.
6. The chat agent sends a short channel-native reply back to WhatsApp.
7. If the lead is qualified or needs human judgment, the owner receives a Telegram summary with extracted profile fields and recent transcript.
