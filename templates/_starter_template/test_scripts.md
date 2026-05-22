# Starter Template Test Scripts

Replace every placeholder before using these scripts in a client demo.

## Hot Lead

```text
Name: {{HOT_LEAD_NAME}}
Email: {{HOT_LEAD_EMAIL}}
Company: {{HOT_LEAD_COMPANY}}
Service interest: {{PRIMARY_SERVICE}}
Message: {{HOT_LEAD_MESSAGE_WITH_URGENCY_AND_FIT}}
Budget: {{HOT_LEAD_BUDGET_OR_VOLUME}}
Timeline: {{HOT_LEAD_TIMELINE}}
```

Expected result:

```text
The lead is qualified, owner approval is requested when the draft includes booking, pricing, or high-risk commitments, and the owner handoff is clear.
```

## Medium Lead

```text
Name: {{MEDIUM_LEAD_NAME}}
Email: {{MEDIUM_LEAD_EMAIL}}
Company: {{MEDIUM_LEAD_COMPANY}}
Service interest: {{PRIMARY_SERVICE}}
Message: {{MEDIUM_LEAD_MESSAGE_WITH_MISSING_INFO}}
Budget: {{MEDIUM_LEAD_BUDGET_OR_VOLUME}}
Timeline: {{MEDIUM_LEAD_TIMELINE}}
```

Expected result:

```text
The system asks a short clarification question or flags what the owner needs to review.
```

## Not-Fit Lead

```text
Name: {{NOT_FIT_LEAD_NAME}}
Email: {{NOT_FIT_LEAD_EMAIL}}
Company: {{NOT_FIT_LEAD_COMPANY}}
Service interest: {{OUT_OF_SCOPE_SERVICE}}
Message: {{NOT_FIT_LEAD_MESSAGE}}
Budget: {{NOT_FIT_BUDGET_OR_VOLUME}}
Timeline: {{NOT_FIT_TIMELINE}}
```

Expected result:

```text
The lead is marked not fit, no booking push is made, and the system does not keep the conversation open with generic nurture language.
```
