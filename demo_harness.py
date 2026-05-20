from __future__ import annotations

import json
import sys

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agents.supervisor import build_supervisor


def main() -> int:
    lead_id = sys.argv[1] if len(sys.argv) > 1 else "lead_001"
    agent = build_supervisor(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"demo-{lead_id}"}}

    request = (
        f"Run the lead intake workflow for {lead_id}. "
        "Qualify it, find missing info, draft the reply, save the CRM note, "
        "save artifacts, and then request sending the follow-up email."
    )
    result = agent.invoke({"messages": [{"role": "user", "content": request}]}, config=config)
    print(json.dumps(result.get("__interrupt__", result), indent=2, default=str))

    if "__interrupt__" in result:
        print("\nInterrupted for human approval. Approving the pending email send...\n")
        resumed = agent.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )
        print(json.dumps(resumed.get("structured_response", resumed), indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
