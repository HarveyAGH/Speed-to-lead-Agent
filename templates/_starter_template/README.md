# Speed-To-Lead Starter Template

This is a starter only. It is not a finished niche template.

## How To Use It

1. Copy this folder to a new niche or client folder, for example `templates/{{NICHE_NAME}}`.
2. Edit `agency_profile.json` first. This file controls qualification, bad-fit logic, urgency, and safety rules.
3. Edit `owner_configuration.json` second. This file controls owner identity, sender identity, calendar link, timezone, and approval notes.
4. Write realistic hot, medium, and not-fit examples in `test_scripts.md`.
5. Copy the finished `agency_profile.json` and `owner_configuration.json` into `mock_data/` for local testing.
6. Run the smoke tests from the main README and client checklist before showing a client.

Keep reusable industry logic in the template. Keep private one-off client wording only in the client-specific copy.

## Key Names vs Values

Most customization should change JSON values, not JSON key names.

Example:

```json
"agency_name": "Clearview Dental"
```

Even though `agency_name` sounds agency-specific, treat it as the current internal key for "the business this agent represents." For a clinic, put the clinic name there. For a law firm, put the law firm name there. For a roofer, put the roofing company name there.

Why keep the key?

```text
Some Python helpers and prompts already pass/read agency_profile.agency_name.
If you rename the key without updating the code and prompts, the LLM may stop seeing the business identity.
```

If you want to rename a key, first search the repo:

```bash
grep -RIn "agency_name" prompts agents tools workflow_nodes.py worker.py app.py
```

Then update every code helper and prompt that depends on it.

## Code-Read Keys

These keys are more sensitive because code or prompt context helpers expect them:

```text
agency_profile.json:
- agency_name
- services
- ideal_customer_profile
- required_fields_for_sales_call
- helpful_fields
- urgent_lead_signals
- qualification_rules
- safety_rules

owner_configuration.json:
- owner_name
- business_name
- sender_name
- sender_title
- discovery_call_url
- timezone
- approval_channel
- approval_policy_note
```

Safe approach:

```text
Change values freely.
Remove or rename keys only after checking CLIENT_SETUP_CHECKLIST.md and searching the repo.
```

## Budget And Timeline Are Business Choices

If a client does not want to ask budget or timeline early, do not blindly delete every budget/timeline concept.

Better approach:

```text
1. Remove budget or timeline from required_fields_for_sales_call.
2. Add a policy rule explaining when to ask for it.
3. Update prompts/speed_to_lead_chat.md if the live chat should behave differently.
4. Update prompts/lead_qualifier.md or prompts/missing_info_detector.md only if form leads should behave differently.
5. Test hot, medium, and not-fit examples.
```

Example:

```json
"required_fields_for_sales_call": [
  "service_interest",
  "website"
],
"qualification_rules": {
  "hot": "Strong pain + enough lead volume + urgent timeline. Budget can be collected later.",
  "medium": "Real business but missing lead volume, urgency, or decision-maker clarity.",
  "not_fit": "Vendor pitch, job seeker, unsupported request, or no real business need."
}
```

## Prompt Files To Check When Customizing

Messaging workflow:

```text
prompts/speed_to_lead_chat.md
```

Use this when changing how WhatsApp/Telegram conversations should greet, qualify, ask questions, send calendar links, close not-fit leads, or escalate to the owner.

Form workflow:

```text
prompts/lead_qualifier.md
prompts/missing_info_detector.md
prompts/followup_writer.md
prompts/crm_recorder.md
```

Use these when changing how Tally/form leads are classified, what missing info matters, or how email-style follow-ups should be written.

Form field mapping:

```text
app.py -> _normalize_field_name()
app.py -> normalize_lead_payload()
```

Use these when changing Tally labels or adding a new internal field.

Channel context:

```text
worker.py -> _channel_agency_profile_context()
workflow_nodes.py -> form workflow context helpers
```

Use these when adding new agency_profile keys that the LLM must reliably see.
