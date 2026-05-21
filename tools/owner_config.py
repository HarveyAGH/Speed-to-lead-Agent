from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from config import OWNER_CONFIG_PATH


DEFAULT_OWNER_CONFIG: dict[str, Any] = {
    "owner_name": "Business Owner",
    "business_name": "Speed-to-Lead Demo",
    "sender_name": "Alex Rivera",
    "sender_title": "Owner",
    "discovery_call_url": "",
    "timezone": "Asia/Manila",
    "approval_channel": "telegram",
    "approval_policy_note": (
        "Safe first responses can be auto-sent. Sales commitments, pricing promises, "
        "discounts, or uncertain cases require owner approval."
    ),
}


@lru_cache(maxsize=1)
def get_owner_config() -> dict[str, Any]:
    if not OWNER_CONFIG_PATH.exists():
        return dict(DEFAULT_OWNER_CONFIG)

    try:
        loaded = json.loads(OWNER_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_OWNER_CONFIG)

    if not isinstance(loaded, dict):
        return dict(DEFAULT_OWNER_CONFIG)

    config = dict(DEFAULT_OWNER_CONFIG)
    config.update({key: value for key, value in loaded.items() if value not in ("", None)})
    return config


def owner_label() -> str:
    config = get_owner_config()
    return str(config.get("owner_name") or DEFAULT_OWNER_CONFIG["owner_name"])


def business_label() -> str:
    config = get_owner_config()
    return str(config.get("business_name") or DEFAULT_OWNER_CONFIG["business_name"])
