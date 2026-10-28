"""Small helper the UI pages use to talk to the SenseDoc API."""

import os

import httpx
import streamlit as st

API_URL = os.getenv("SENSEDOC_API_URL", "http://localhost:8000")
API_TOKEN = os.getenv("API_TOKEN", "")  # must match the API's API_TOKEN when that is set

STATUS_ICONS = {
    "queued": ":material/schedule:",
    "processing": ":material/autorenew:",
    "needs_review": ":material/rate_review:",
    "done": ":material/check_circle:",
    "failed": ":material/error:",
}


@st.cache_resource
def http() -> httpx.Client:
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    return httpx.Client(base_url=API_URL, timeout=120, headers=headers)


def get(path: str, **params):
    response = http().get(path, params={k: v for k, v in params.items() if v is not None})
    response.raise_for_status()
    return response.json()


def send(method: str, path: str, **kwargs):
    response = http().request(method, path, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(response.json().get("detail", response.text))
    return response.json()


@st.cache_data(ttl=600, max_entries=300, show_spinner=False)
def preview_png(document_id: int, page: int = 1, value_id: int | None = None) -> bytes | None:
    """A page image; with value_id, that value is boxed where it was found."""
    params = {"page": page, **({"value_id": value_id} if value_id else {})}
    response = http().get(f"/documents/{document_id}/preview", params=params)
    return response.content if response.status_code == 200 else None


def require_api() -> None:
    try:
        http().get("/health").raise_for_status()
    except httpx.HTTPError:
        st.error(
            f"Start it with `uv run uvicorn sensedoc.api:app` and refresh this page. Expected at {API_URL}.",
            title="The SenseDoc API is not running",
            icon=":material/cloud_off:",
        )
        st.stop()


def status_label(status: str) -> str:
    return f"{STATUS_ICONS.get(status, '')} {status.replace('_', ' ')}"
