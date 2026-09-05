from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Required environment variable {name!r} is not set. Check your .env file.")
    return val


SUPABASE_URL: str = _require("SUPABASE_URL")
SUPABASE_KEY: str = _require("SUPABASE_KEY")
DONOR_SALT: str = _require("DONOR_SALT")
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "100"))

# Anthropic — not required at import time; AnthropicClient raises if missing at call time
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY") or None
ANTHROPIC_MODEL_SELECTION: str = os.getenv("ANTHROPIC_MODEL_SELECTION", "claude-haiku-4-5")
ANTHROPIC_MODEL_ASSEMBLY: str = os.getenv("ANTHROPIC_MODEL_ASSEMBLY", "claude-sonnet-4-6")
ANTHROPIC_MODEL_JUDGE: str = os.getenv("ANTHROPIC_MODEL_JUDGE", "claude-haiku-4-5")

ASYNC_CONCURRENCY: int = int(os.getenv("ASYNC_CONCURRENCY", "20"))
COST_TRACKING_ENABLED: bool = os.getenv("COST_TRACKING_ENABLED", "true").lower() == "true"
ENABLE_PROMPT_CACHING: bool = os.getenv("ENABLE_PROMPT_CACHING", "true").lower() == "true"

DONOR_INSERT_CHUNK = 100

CENTERS = [
    "BioLife Bengaluru",
    "BioLife Mumbai",
    "BioLife Delhi",
    "BioLife Hyderabad",
    "BioLife Pune",
]
