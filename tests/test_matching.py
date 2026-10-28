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


# ---------- meaning fallback (embeddings), with a fake model so tests need no API ----------
def fake_meaning(table: dict[str, dict[str, float]]):
    calls = []

    def meaning(query, options):
        calls.append(query)
        return [table.get(query, {}).get(o, 0.70) for o in options]

    meaning.calls = calls
    return meaning


def test_meaning_matches_a_synonym_spelling_cannot(catalogue):
    meaning = fake_meaning({"Coca-Cola Light": {"Coca-Cola Diet": 0.87, "Coca-Cola Original": 0.74, "Coca-Cola Zero Sugar": 0.75}})
    m = match_row(row(brand="Coca-Cola", flavour="Light", size="33cl", pack_type="can", pack_count=1), catalogue, meaning)
    assert m.sku == "CC-DIET-330-CAN"
    assert "meaning" in m.reason and m.confidence >= 0.8


def test_meaning_never_guesses_between_close_options(catalogue):
    # 'Cherry' is not in the catalogue: every option scores alike, so it must go to review
    meaning = fake_meaning({"Coca-Cola Cherry": {"Coca-Cola Diet": 0.748, "Coca-Cola Original": 0.744, "Coca-Cola Zero Sugar": 0.742}})
    m = match_row(row(brand="Coca-Cola", flavour="Cherry", size="33cl", pack_type="can", pack_count=1), catalogue, meaning)
    assert m.sku is None


def test_without_embeddings_it_falls_back_to_review(catalogue):
    m = match_row(row(brand="Coca-Cola", flavour="Light", size="33cl", pack_type="can", pack_count=1), catalogue, lambda q, o: None)
    assert m.sku is None


def test_meaning_is_not_asked_when_only_the_size_is_missing(catalogue):
    meaning = fake_meaning({})
    m = match_row(row(brand="Coca-Cola", flavour="Zero", pack_type="can", pack_count=1), catalogue, meaning)
    assert m.sku is None and "size" in m.reason
    assert meaning.calls == []  # spelling already settled the flavour; no API call wasted


def test_meaning_never_decides_with_a_single_option(catalogue):
    # a 35cl Fanta can only exists as Orange; 'Citrus' is a different product, so a person must decide
    meaning = fake_meaning({"Fanta Citrus": {"Fanta Orange": 0.85}})
    m = match_row(row(brand="Fanta", flavour="Citrus", size="35cl", pack_type="can", pack_count=1), catalogue, meaning)
    assert m.sku is None
    assert meaning.calls == []
