# Failure Notes

Use this file during testing. A sellable demo needs proof that bad outputs were noticed and retested.

## Case Template

```text
Case:
Expected behavior:
Actual behavior:
Why it was bad:
How it was detected:
Fix:
Retest:
```

## Seed Failure Cases To Test

### Vendor pitch should not be treated as a sales lead

Expected behavior:
`lead_003` should be classified as `spam_or_vendor` or `bad_fit`, with `disqualify` as the next action.

Retest:
Run the workflow for `lead_003` and confirm no sales-style follow-up is recommended.

### Missing budget should trigger clarification

Expected behavior:
`lead_002` should not be scored as high-fit until the budget is clarified.

Retest:
Run the workflow for `lead_002` and confirm the draft asks only the minimum missing questions.

### Strong lead should get fast-call recommendation

Expected behavior:
`lead_001` should be high-fit, urgent, and recommended for a discovery call.

Retest:
Run the workflow for `lead_001` and confirm the CRM note and draft message are saved.
