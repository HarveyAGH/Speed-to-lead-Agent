# Token Baseline

This file records the architecture/token comparison after replacing the open-ended supervisor workflow with an explicit LangGraph `StateGraph` pipeline.

## Baseline Numbers

| Workflow version | Tokens | Estimated cost | Notes |
| --- | ---: | ---: | --- |
| Older supervisor-style workflow | 49.2K | not recorded here | Supervisor had more freedom to plan, route, and repeatedly pass context through model calls. |
| Explicit StateGraph pipeline | 18K | $0.027202 | Root trace for `lead_4a84q6B` in LangSmith. |

## Reduction

```text
49.2K - 18K = 31.2K fewer tokens
31.2K / 49.2K * 100 = 63.4% reduction
```

## Why It Improved

The new graph reduced token usage because orchestration is deterministic now.

The old pattern asked the supervisor model to decide the workflow path. That meant the model had to repeatedly reason over the task, tool outputs, and routing decisions.

The new pattern makes the workflow path explicit:

```text
load_lead
-> qualify
-> detect_missing
-> draft_followup
-> save_crm_note
-> save_artifacts
-> route by send_policy
-> send / approval_gate / do_not_send
-> final_summary
```

The LLM is now used only where language judgment is needed:

- qualification
- missing-info detection
- follow-up drafting
- CRM note generation

The graph handles orchestration, routing, persistence, and approval boundaries without asking the LLM to manage those steps.

## Practical Interpretation

At 18K tokens and about $0.0272 per lead:

```text
1,000 leads/month * $0.0272 = about $27.20/month in LLM cost
```

That is commercially acceptable for a monthly automation retainer, assuming the client pays hundreds or thousands per month.

## What To Watch Next

- If one simple lead starts costing more than 25K tokens, inspect for repeated model calls or bloated context.
- If output tokens are high, tighten agent response formats.
- If input tokens are high, reduce prompt size and avoid passing unnecessary history.
- If latency matters, reduce model calls before changing infrastructure.
