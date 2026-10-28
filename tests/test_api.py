"""The whole loop through the REST API, with the LLM call replaced by a fake answer."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sensedoc import pipeline
from sensedoc.api import app
from sensedoc.extractor import ExtractionOutput
from sensedoc.schema_builder import build_model

ROOT = Path(__file__).resolve().parents[1]

FAKE_INVOICE = {
    "invoice_number": "INV-2026-0147",
    "invoice_date": "2026-10-14",
    "supplier": "ADEBAYO SUPPLIES LTD",
    "subtotal": 21000,
    "tax": 1575,
    "total_amount": 99999,  # wrong on purpose: the sum rule must catch it
    "items": [
        {"product": "Coca-Cola Original 50cl PET", "quantity": 24, "unit_price": 500, "line_total": 12000},
        {"product": "Fanta Orange 35cl Can", "quantity": 12, "unit_price": 350, "line_total": 4200},
        {"product": "Pepsi 1L PET", "quantity": 6, "unit_price": 800, "line_total": 4800},
    ],
}


@pytest.fixture()
def client(monkeypatch):
    def fake_extract(doc, template, models=None):
        data = build_model("Extraction", template.fields)(**FAKE_INVOICE)
        return ExtractionOutput(data=data, model="fake", tokens_in=100, tokens_out=50, latency_ms=10, attempts=1)

    monkeypatch.setattr(pipeline, "extract", fake_extract)
    with TestClient(app) as c:
        yield c


def test_full_loop(client):
    templates = {t["name"]: t["id"] for t in client.get("/templates").json()}
    assert {"Supplier Invoice", "Shop Receipt", "Product Price List"} <= set(templates)

    with open(ROOT / "samples" / "invoice_001.pdf", "rb") as f:
        created = client.post("/documents", data={"template_id": templates["Supplier Invoice"]}, files=[("files", f)]).json()
    doc = client.get(f"/documents/{created[0]['id']}").json()
    assert doc["status"] == "needs_review"

    queue = client.get("/review-queue").json()
    total = next(v for v in queue if v["field_path"] == "total_amount")
    fixed = client.patch(f"/values/{total['id']}", json={"action": "correct", "new_value": "22,575.00", "reviewer": "test"})
    assert fixed.json()["value"] == 22575.0

    # approve whatever else the sum rule flagged
    for v in client.get("/review-queue").json():
        client.patch(f"/values/{v['id']}", json={"action": "approve"})
    assert client.get(f"/documents/{doc['id']}").json()["status"] == "done"

    csv = client.get(f"/templates/{templates['Supplier Invoice']}/export?format=csv").text
    assert ",22575," in csv and csv.count("\n") == 4  # header + 3 item rows

    metrics = client.get("/metrics").json()
    assert metrics["documents"]["done"] >= 1


def test_template_edit_creates_new_version(client):
    first = client.get("/templates").json()[0]
    body = {**first["template"], "document_type": "edited"}
    edited = client.put(f"/templates/{first['id']}", json=body).json()
    assert edited["version"] == first["version"] + 1
    assert client.get(f"/templates/{first['id']}").json()["template"]["document_type"] != "edited"


def test_rejects_unsupported_files(client):
    response = client.post("/documents", data={"template_id": 1}, files=[("files", ("notes.exe", b"x"))])
    assert response.status_code == 415
