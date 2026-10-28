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

# SQLite works out of the box; Docker Compose sets this to PostgreSQL, and Supabase is PostgreSQL too
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'sensedoc.db'}")
for _plain in ("postgres://", "postgresql://"):  # Supabase gives "postgresql://..."; SQLAlchemy needs the driver name
    if DATABASE_URL.startswith(_plain):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix(_plain)
IS_POSTGRES = DATABASE_URL.startswith("postgresql")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", PROJECT_ROOT / "storage"))

# when set, jobs go to Celery workers through Redis; otherwise they run inside the API process
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")

MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "20"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "30"))

# read photos and scans with OCR too: gives value positions and confirms values read from images
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() == "true"
# what the LLM gets for photos and scans: "vision" (the image), "ocr" (OCR text only), "hybrid" (both)
EXTRACTION_ROUTE = os.getenv("EXTRACTION_ROUTE", "vision")

# security: when API_TOKEN is set, every API call (except the landing page and health check) needs it
API_TOKEN = os.getenv("API_TOKEN", "")
# privacy: uploaded files older than this many days are deleted (extracted data is kept); 0 keeps them
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "0"))

# knowledge assistant: page text is embedded so questions can find relevant passages by meaning
EMBEDDINGS_ENABLED = os.getenv("EMBEDDINGS_ENABLED", "true").lower() == "true"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
EMBED_DIMS = 768  # changing this needs a re-index (POST /assistant/reindex)

# Supabase Storage for uploaded files (optional; without it files stay on local disk)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # server-side secret key: never put it in the UI
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "documents")
