from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from config import PROMPT_DIR
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBinding


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


def build_structured_chain(model: Any, prompt_name: str, schema: type[Any]):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt(prompt_name)),
            ("human", "{input}"),
        ]
    )
    base_model = model.bound if isinstance(model, RunnableBinding) else model
    structured_model = base_model.with_structured_output(schema)
    return (prompt | structured_model).with_retry(
        stop_after_attempt=3,
        wait_exponential_jitter=True,
    )


def dump_structured_result(result: Any) -> str:
    if hasattr(result, "model_dump_json"):
        return result.model_dump_json(indent=2)
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), indent=2)
    if isinstance(result, dict):
        return json.dumps(result, indent=2)
    return str(result)
