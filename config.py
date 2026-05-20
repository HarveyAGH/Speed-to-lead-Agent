from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_aws import ChatBedrock


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)


BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")

llm = ChatBedrock(
    model_id=BEDROCK_MODEL_ID,
    region_name=BEDROCK_REGION,
)



MODEL: Any = llm
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(PROJECT_ROOT / "outputs")))
MOCK_DATA_DIR = Path(os.getenv("MOCK_DATA_DIR", str(PROJECT_ROOT / "mock_data")))
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
AIRTABLE_AGENT_RUNS_TABLE = os.getenv("AIRTABLE_AGENT_RUNS_TABLE", "Agent Runs")
WEBHOOK_SHARED_SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
POSTGRES_DB_URI = os.getenv("POSTGRES_DB_URI", "")

MAX_WEBHOOK_BODY_BYTES = int(os.getenv("MAX_WEBHOOK_BODY_BYTES", "262144"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
