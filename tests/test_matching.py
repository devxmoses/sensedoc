"""The worked examples from the project plan's 'Product and variant recognition' section."""

import csv
from pathlib import Path

import pytest

from sensedoc.matching import Product, match_row, unit_price

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalogue():
    with open(ROOT / "samples" / "catalogue.csv") as f:
        return [
            Product(r["sku"], r["brand"], r["type"], float(r["size_ml"]), r["pack_type"], int(r["pack_count"]),
                    [a for a in r["brand_aliases"].split(";") if a])
            for r in csv.DictReader(f)
        ]


def row(**kw):
    return {"product_text": None, "brand": None, "flavour": None, "size": None, "pack_type": None, "pack_count": None, **kw}


def test_full_attributes_auto_match(catalogue):
    m = match_row(row(brand="Coke", flavour="Original", size="50cl", pack_type="PET", pack_count=1), catalogue)
    assert m.sku == "CC-ORIG-500-PET"


def test_missing_size_goes_to_review_with_candidates(catalogue):
    m = match_row(row(brand="Coca-Cola", flavour="Zero", pack_type="can", pack_count=1), catalogue)
    assert m.sku is None
    assert "size" in m.reason
    assert {c["sku"] for c in m.candidates} == {"CC-ZERO-330-CAN", "CC-ZERO-350-CAN"}


def test_multipack_and_unit_price(catalogue):
    r = row(brand="Coke", flavour="Original", size="35cl", pack_type="can", pack_count=12, price=5400, price_basis="per pack")
    m = match_row(r, catalogue)
    assert m.sku == "CC-ORIG-350-CAN-12"
    assert unit_price(r, next(p for p in catalogue if p.sku == m.sku)) == 450


def test_brand_only_never_guesses(catalogue):
    m = match_row(row(brand="Coke"), catalogue)
    assert m.sku is None
    assert len(m.candidates) == 3  # top three shown to the reviewer


def test_zero_and_original_are_not_confused(catalogue):
    m = match_row(row(brand="Coca-Cola", flavour="Zero Sugar", size="50cl", pack_type="PET", pack_count=1), catalogue)
    assert m.sku == "CC-ZERO-500-PET"


def test_learned_alias_wins(catalogue):
    learned = [p if p.sku != "CC-ZERO-350-CAN" else Product(**{**p.__dict__, "aliases": ["coke zero can"]}) for p in catalogue]
    m = match_row(row(product_text="Coke Zero Can", brand="Coca-Cola", flavour="Zero", pack_type="can"), learned)
    assert m.sku == "CC-ZERO-350-CAN"
