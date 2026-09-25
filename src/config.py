"""Application configuration loaded from environment / .env."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip() or default)
    except (ValueError, AttributeError):
        return default


INPUT_DIR = os.getenv("INPUT_DIR", "./input")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")

AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "").strip() or None
AI_MODEL = os.getenv("AI_MODEL", "").strip() or "gpt-4o-mini"
MAX_AI_RETRIES = _int("MAX_AI_RETRIES", 2)


def ai_enabled() -> bool:
    """AI is available only when an API key is configured."""
    return bool(AI_API_KEY)
