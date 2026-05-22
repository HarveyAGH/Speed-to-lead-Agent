from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from config import OUTPUT_DIR

SAFE_PATH_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_-]")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_path_component(
    value: object,
    *,
    fallback: str = "item",
    limit: int | None = None,
) -> str:
    text = "" if value is None else str(value)
    safe = SAFE_PATH_COMPONENT_RE.sub("_", text).strip("_")
    if not safe:
        safe = fallback
    if limit is not None:
        safe = safe[:limit].strip("_") or fallback
    return safe


def new_run_id(prefix: str = "run") -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    prefix = safe_path_component(prefix, fallback="run")
    return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"


def write_json(path: Path, payload: dict | list) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


def write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def output_run_dir(run_id: str) -> Path:
    output_root = OUTPUT_DIR.resolve()
    run_dir = (output_root / run_id).resolve()
    if run_dir != output_root and output_root not in run_dir.parents:
        raise ValueError(f"Output run directory escapes OUTPUT_DIR: {run_id}")
    return run_dir
