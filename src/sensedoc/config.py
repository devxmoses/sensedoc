"""All settings in one place, read from environment variables (or .env)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
# a second model to try when the first one fails or is overloaded
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash")

# USD per 1 million tokens. Check https://ai.google.dev/gemini-api/docs/pricing
PRICE_INPUT_PER_M = float(os.getenv("PRICE_INPUT_PER_M", "1.50"))
PRICE_OUTPUT_PER_M = float(os.getenv("PRICE_OUTPUT_PER_M", "7.50"))

# SQLite works out of the box; Docker Compose sets this to PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'sensedoc.db'}")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", PROJECT_ROOT / "storage"))

# when set, jobs go to Celery workers through Redis; otherwise they run inside the API process
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")

MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "20"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "30"))
