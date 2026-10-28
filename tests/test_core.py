"""Fast tests for the core logic. No API key or network needed."""

import copy
from pathlib import Path

import pytest

from sensedoc.normalize import volume_to_ml
from sensedoc.readers import read_document
from sensedoc.schema_builder import Template, TemplateField, build_model, to_key
from sensedoc.validator import document_status, validate

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Template.model_validate_json((ROOT / "templates" / "invoice.json").read_text())
Extraction = build_model("Extraction", TEMPLATE.fields)

CORRECT = {
    "invoice_number": "INV-2026-0147",
    "invoice_date": "2026-10-14",
    "supplier": "ADEBAYO SUPPLIES LTD",
    "subtotal": 21000,
    "tax": 1575,
    "total_amount": 22575,
    "items": [
        {"product": "Coca-Cola Original 50cl PET", "quantity": 24, "unit_price": 500, "line_total": 12000},
        {"product": "Fanta Orange 35cl Can", "quantity": 12, "unit_price": 350, "line_total": 4200},
        {"product": "Pepsi 1L PET", "quantity": 6, "unit_price": 800, "line_total": 4800},
    ],
}


@pytest.fixture(scope="module")
def invoice_doc():
    return read_document(ROOT / "samples" / "invoice_001.pdf")


@pytest.mark.parametrize(
    "name, key",
    [("Invoice Number", "invoice_number"), ("Price (₦)", "price"), ("50cl Price", "f_50cl_price")],
)
def test_to_key(name, key):
    assert to_key(name) == key


def test_build_model_with_table():
    model = build_model("X", [TemplateField(name="Items", type="table", columns=[TemplateField(name="Unit Price", type="currency")])])
    data = model(items=[{"unit_price": "350"}])
    assert data.items[0].unit_price == 350.0


@pytest.mark.parametrize("text, ml", [("50cl", 500), ("1.5L", 1500), ("Coke 35 cl x12", 350), ("500ml", 500), ("big bottle", None)])
def test_volume_to_ml(text, ml):
    assert volume_to_ml(text) == ml


def test_correct_invoice_is_done(invoice_doc):
    results = validate(Extraction(**CORRECT), TEMPLATE, invoice_doc)
    assert document_status(results) == "done"
    assert all(r.confidence == 1.0 for r in results)


def test_misread_number_breaks_the_sum_rule(invoice_doc):
    data = copy.deepcopy(CORRECT)
    data["items"][1]["line_total"] = 4800  # printed elsewhere on the page, so grounding alone passes
    flagged = {r.name for r in validate(Extraction(**data), TEMPLATE, invoice_doc) if r.status == "needs_review"}
    assert flagged == {"subtotal", "items[0].line_total", "items[1].line_total", "items[2].line_total"}


def test_invented_value_is_not_grounded(invoice_doc):
    data = {**CORRECT, "invoice_number": "INV-2026-9999"}
    result = next(r for r in validate(Extraction(**data), TEMPLATE, invoice_doc) if r.name == "invoice_number")
    assert result.status == "needs_review"
    assert "not found" in result.issues[0]


def test_missing_required_field(invoice_doc):
    data = {**CORRECT, "invoice_date": None}
    result = next(r for r in validate(Extraction(**data), TEMPLATE, invoice_doc) if r.name == "invoice_date")
    assert result.confidence == 0.0


def test_image_values_get_lower_confidence():
    doc = read_document(ROOT / "samples" / "invoice_001_photo.png")
    results = validate(Extraction(**CORRECT), TEMPLATE, doc)
    assert {round(r.confidence, 2) for r in results} == {0.85}
    assert document_status(results) == "done"
