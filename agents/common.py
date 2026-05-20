from __future__ import annotations

from pathlib import Path
import json

from config import PROMPT_DIR


def load_prompt(name: str) -> str:
    return Path(PROMPT_DIR, name).read_text(encoding="utf-8")


def structured_or_last_message(result: dict) -> str:
    structured = result.get("structured_response")
    if structured is not None:
        return structured.model_dump_json(indent=2)

    message = result["messages"][-1]
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    return str(content)


def require_json_text(value: str, field_name: str) -> str | None:
    if not value or not value.strip():
        return json.dumps(
            {
                "error": "missing_required_input",
                "field": field_name,
                "message": f"Call this subagent again with `{field_name}` populated.",
            },
            indent=2,
        )
    return None
