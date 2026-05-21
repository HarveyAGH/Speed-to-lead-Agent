from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from langchain_aws import ChatBedrockConverse
except ImportError:
    ChatBedrockConverse = None
    from langchain_aws import ChatBedrock


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)


BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")

if ChatBedrockConverse is not None:
    llm = ChatBedrockConverse(
        model=BEDROCK_MODEL_ID,
        region_name=BEDROCK_REGION,
    )
else:
    llm = ChatBedrock(
        model_id=BEDROCK_MODEL_ID,
        region_name=BEDROCK_REGION,
    )


MODEL: Any = llm
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(PROJECT_ROOT / "outputs")))
MOCK_DATA_DIR = Path(os.getenv("MOCK_DATA_DIR", str(PROJECT_ROOT / "mock_data")))
AGENCY_PROFILE_PATH = Path(
    os.getenv(
        "AGENCY_PROFILE_PATH",
        str(MOCK_DATA_DIR / "agency_profile.json"),
    )
)
PROMPT_DIR = Path(os.getenv("PROMPT_DIR", str(PROJECT_ROOT / "prompts")))
OWNER_CONFIG_PATH = Path(
    os.getenv(
        "OWNER_CONFIG_PATH",
        str(MOCK_DATA_DIR / "owner_configuration.json"),
    )
)

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
AIRTABLE_LEADS_TABLE = os.getenv("AIRTABLE_LEADS_TABLE", "Leads")
AIRTABLE_AGENT_RUNS_TABLE = os.getenv("AIRTABLE_AGENT_RUNS_TABLE", "Agent_runs")
WEBHOOK_SHARED_SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_ALLOW_OWNER_AS_LEAD = (
    os.getenv("TELEGRAM_ALLOW_OWNER_AS_LEAD", "").strip().lower()
    in {"1", "true", "yes", "on"}
)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
POSTGRES_DB_URI = os.getenv("POSTGRES_DB_URI", "")

MAX_WEBHOOK_BODY_BYTES = int(os.getenv("MAX_WEBHOOK_BODY_BYTES", "262144"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
STALE_JOB_MINUTES = int(os.getenv("STALE_JOB_MINUTES", "10"))

CHANNEL_CONTEXT_MAX_CHARS = int(os.getenv("CHANNEL_CONTEXT_MAX_CHARS", "4000"))
CHANNEL_MESSAGE_MAX_CHARS = int(os.getenv("CHANNEL_MESSAGE_MAX_CHARS", "600"))
CHANNEL_PROFILE_MAX_CHARS = int(os.getenv("CHANNEL_PROFILE_MAX_CHARS", "1500"))
