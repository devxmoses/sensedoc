"""Supabase Storage, against a fake Supabase server (no account needed)."""

import json

import httpx
import pytest

from sensedoc import config, storage


@pytest.fixture()
def fake_supabase(monkeypatch):
    objects: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == "service-key"
        path = request.url.path.removeprefix("/storage/v1")
        if request.method == "POST" and path == "/bucket":
            return httpx.Response(200, json={"name": "documents"})
        if request.method == "POST" and path.startswith("/object/"):
            objects[path.removeprefix("/object/")] = request.content
            return httpx.Response(200, json={"Key": path})
        if request.method == "GET" and path.startswith("/object/"):
            key = path.removeprefix("/object/")
            return httpx.Response(200, content=objects[key]) if key in objects else httpx.Response(400, json={"error": "not found"})
        if request.method == "DELETE":
            bucket = path.removeprefix("/object/")
            for key in json.loads(request.content)["prefixes"]:
                objects.pop(f"{bucket}/{key}", None)
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(
        storage, "_client",
        lambda: httpx.Client(base_url="https://example.supabase.co/storage/v1", transport=httpx.MockTransport(handler),
                             headers={"Authorization": "Bearer service-key", "apikey": "service-key"}),
    )
    return objects


def test_files_go_to_supabase_when_configured(fake_supabase):
    ref = storage.save("abc.pdf", b"%PDF-1.7 test", "application/pdf")
    assert ref == "supabase://documents/abc.pdf"
    assert fake_supabase["documents/abc.pdf"] == b"%PDF-1.7 test"
    assert storage.read_bytes(ref) == b"%PDF-1.7 test"

    with storage.local_copy(ref) as path:  # libraries like PyMuPDF get a real file
        assert path.suffix == ".pdf" and path.read_bytes() == b"%PDF-1.7 test"
    assert not path.exists()  # the temporary copy is cleaned up

    storage.delete(ref)
    assert not storage.exists(ref)


def test_local_disk_without_supabase(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    ref = storage.save("a.png", b"png-bytes")
    assert ref == str(tmp_path / "a.png") and storage.read_bytes(ref) == b"png-bytes"
    storage.delete(ref)
    assert not storage.exists(ref)
