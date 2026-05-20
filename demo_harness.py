from __future__ import annotations

import json
import sys

from langgraph.types import Command

from graph import graph


def main() -> int:
    lead_id = sys.argv[1] if len(sys.argv) > 1 else "lead_001"
    config = {"configurable": {"thread_id": f"demo-{lead_id}"}}

    result = graph.invoke({"lead_id": lead_id}, config=config)
    print(json.dumps(result.get("__interrupt__", result), indent=2, default=str))

    if "__interrupt__" in result:
        print("\nInterrupted for human approval. Approving the pending email send...\n")
        resumed = graph.invoke(
            Command(resume="approve"),
            config=config,
        )
        print(json.dumps(resumed, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
