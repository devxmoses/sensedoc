"""Where uploaded files live: the local disk, or Supabase Storage when it is configured.

Hosting platforms wipe a container's disk on every restart, so a hosted SenseDoc keeps files in
Supabase Storage. Every file is referred to by a 'ref' string stored in documents.storage_path:
    a local path               /app/storage/3f2a....pdf
    a Supabase object          supabase://documents/3f2a....pdf
"""

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import httpx

from sensedoc import config

PREFIX = "supabase://"


def supabase_enabled() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _client() -> httpx.Client:
    key = config.SUPABASE_SERVICE_KEY
    return httpx.Client(
        base_url=f"{config.SUPABASE_URL.rstrip('/')}/storage/v1",
        headers={"Authorization": f"Bearer {key}", "apikey": key},
        timeout=120,
    )


def _split(ref: str) -> tuple[str, str]:
    bucket, _, key = ref.removeprefix(PREFIX).partition("/")
    return bucket, key


def ensure_bucket() -> None:
    """Create the private bucket on first start (an existing one is left alone)."""
    if supabase_enabled():
        with _client() as client:
            client.post("/bucket", json={"id": config.SUPABASE_BUCKET, "name": config.SUPABASE_BUCKET, "public": False})


def save(name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    if supabase_enabled():
        with _client() as client:
            response = client.post(
                f"/object/{config.SUPABASE_BUCKET}/{name}",
                content=data,
                headers={"Content-Type": content_type, "x-upsert": "true"},
            )
            response.raise_for_status()
        return f"{PREFIX}{config.SUPABASE_BUCKET}/{name}"
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.STORAGE_DIR / name
    path.write_bytes(data)
    return str(path)


def read_bytes(ref: str) -> bytes:
    if ref.startswith(PREFIX):
        bucket, key = _split(ref)
        with _client() as client:
            response = client.get(f"/object/{bucket}/{key}")
            if response.status_code in (400, 404):
                raise FileNotFoundError(ref)
            response.raise_for_status()
            return response.content
    return Path(ref).read_bytes()


def exists(ref: str) -> bool:
    try:
        if ref.startswith(PREFIX):
            read_bytes(ref)
            return True
        return Path(ref).exists()
    except FileNotFoundError:
        return False


def delete(ref: str) -> None:
    if ref.startswith(PREFIX):
        bucket, key = _split(ref)
        with _client() as client:
            client.request("DELETE", f"/object/{bucket}", json={"prefixes": [key]})
    else:
        Path(ref).unlink(missing_ok=True)


@contextmanager
def local_copy(ref: str):
    """A real file path for libraries that need one (PyMuPDF, pandas). Remote files are downloaded, then removed."""
    if not ref.startswith(PREFIX):
        yield Path(ref)
        return
    suffix = Path(ref).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(read_bytes(ref))
    try:
        yield Path(tmp.name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def copy_to(ref: str, destination: Path) -> None:
    with local_copy(ref) as path:
        shutil.copy(path, destination)
