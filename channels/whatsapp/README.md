# WhatsApp Channel

This adapter receives WhatsApp Cloud API webhook messages and turns each inbound text into the same lead payload used by the Tally webhook.

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
3. The message is normalized into a lead with:
   - `source = whatsapp`
   - `source_channel = whatsapp`
   - `channel_user_id = <sender phone number>`
4. `tools.lead_ingestion.ingest_lead()` writes the CRM lead and queues the job.
5. The worker processes the job.
6. If policy allows auto-send, `channels.channel_dispatcher` sends the drafted reply back to WhatsApp.
7. If approval is required, the owner approves in Telegram and the approved draft is sent back to WhatsApp.
