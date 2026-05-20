# What Stays Human

The agent may recommend, draft, save notes, and prepare evidence.

The human owner keeps control of:

- Sending customer-facing emails or messages.
- Editing customer-facing wording.
- Approving CRM status changes that affect sales pipeline reporting.
- Making pricing, discount, or guarantee commitments.
- Booking external calendar slots.
- Disqualifying a lead when the reason is ambiguous.
- Changing qualification rules.
- Connecting production CRM, email, or ad platform accounts.

For this MVP, `send_followup_email` is approval-gated and simulated with a file write. That proves the approval boundary without risking a real customer message.
