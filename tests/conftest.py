import os
import tempfile
from pathlib import Path

# point the app at a throwaway database and folder before any sensedoc module is imported
_tmp = Path(tempfile.mkdtemp(prefix="sensedoc-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["STORAGE_DIR"] = str(_tmp / "storage")
os.environ.pop("CELERY_BROKER_URL", None)

ROOT = Path(__file__).resolve().parents[1]
