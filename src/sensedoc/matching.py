"""Match each extracted product line to one exact SKU in the catalogue, or send it to review.

The rule from the plan: never guess. A row is only matched when exactly one SKU fits.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from sensedoc.normalize import volume_to_ml
from sensedoc.schema_builder import Template, to_key
from sensedoc.ocr import Line
from sensedoc.validator import AUTO_APPROVE_AT, FieldResult, locate, squash

BRAND_MATCH_AT = 85  # 0-100 text similarity needed to count as the same brand
FLAVOUR_MATCH_AT = 70
CLEAR_WINNER_GAP = 15  # top flavour score must beat the runner-up by this much
UNUSED_MISSING_PENALTY = 0.05  # attribute missing, but it didn't matter for this catalogue

# Meaning (embeddings) is only asked when spelling can't decide, e.g. 'Coke Light' vs the 'Diet' SKU.
# Thresholds were measured with gemini-embedding-001 on full product names (see docs/WALKTHROUGH.md).
MEANING_MATCH_AT = 0.78  # best option must reach this...
MEANING_GAP = 0.05  # ...and beat the runner-up by this much
# With only one flavour left there is nothing to compare against: 'Fanta Citrus' scored 0.85 against the only
# option, Orange, higher than the true 'Classic' -> 'Original' (0.84). So one option always goes to review.
MEANING_CONFIDENCE = 0.82  # auto-approved, but the lowest confidence a match can have

# (query, options) -> one similarity per option, or None when embeddings are unavailable
MeaningFn = Callable[[str, list[str]], list[float] | None]

PACK_TYPES = {"can": "can", "tin": "can", "pet": "pet", "plastic": "pet", "glass": "glass", "returnable": "glass"}


@dataclass
class Product:
    sku: str
    brand: str
    type: str
    size_ml: float
    pack_type: str
    pack_count: int = 1
    brand_aliases: list[str] = field(default_factory=list)  # e.g. "Coke" for Coca-Cola
    aliases: list[str] = field(default_factory=list)  # learned from reviewer corrections

    @property
    def name(self) -> str:
        pack = "" if self.pack_count == 1 else f" x{self.pack_count}"
        return f"{self.brand} {self.type} {self.size_ml:g}ml {self.pack_type}{pack}"


@dataclass
class Match:
    sku: str | None
    confidence: float
    reason: str
    candidates: list[dict]


def similarity(a: str, b: str) -> float:
    return fuzz.WRatio(a.lower(), b.lower())


def pack_type_of(text: str | None) -> str | None:
    """'PET bottle' -> 'pet'. A plain 'bottle' could be PET or glass, so it stays unknown."""
    if not text:
        return None
    for word in text.lower().replace("-", " ").split():
        if word in PACK_TYPES:
            return PACK_TYPES[word]
    return None


def row_alias(row: dict) -> str:
    """The wording a reviewer's choice is remembered under."""
    text = row.get("product_text") or " ".join(
        str(row.get(k) or "") for k in ("brand", "flavour", "size", "pack_type", "pack_count")
    )
    return squash(text)


def as_candidates(products: list[Product], scores: dict[str, float], limit: int = 3) -> list[dict]:
    ranked = sorted(products, key=lambda p: scores.get(p.sku, 0), reverse=True)[:limit]
    return [{"sku": p.sku, "name": p.name, "score": round(scores.get(p.sku, 0))} for p in ranked]


def match_by_meaning(row: dict, options: list[Product], meaning: MeaningFn | None) -> Match | None:
    """Compare full names by meaning. Returns a match only when one flavour is clearly closest."""
    if meaning is None or len({p.type for p in options}) < 2:
        return None
    kinds: dict[str, list[Product]] = {}  # one name per flavour: 'Coca-Cola Diet' -> its SKUs
    for p in options:
        kinds.setdefault(f"{p.brand} {p.type}", []).append(p)
    query = f"{row.get('brand') or options[0].brand} {row['flavour']}"
    sims = meaning(query, list(kinds))
    if not sims:
        return None

    ranked = sorted(zip(sims, kinds), reverse=True)
    if len(ranked) < 2:
        return None  # nothing to compare against: a person decides
    best_sim, best_name = ranked[0]
    sure = best_sim >= MEANING_MATCH_AT and best_sim - ranked[1][0] >= MEANING_GAP
    if not sure or len(kinds[best_name]) > 1:  # unsure, or several SKUs (sizes/packs) share that flavour
        return None

    product = kinds[best_name][0]
    scores = {p.sku: round(sim * 100) for sim, name in ranked for p in kinds[name]}
    reason = f"matched by meaning: '{row['flavour']}' ≈ '{product.type}'"
    return Match(product.sku, MEANING_CONFIDENCE, reason, as_candidates(options, scores))


def match_row(row: dict, catalogue: list[Product], meaning: MeaningFn | None = None) -> Match:
    # 1. A reviewer already told us what this exact wording means
    alias = row_alias(row)
    for product in catalogue:
        if alias and alias in product.aliases:
            return Match(product.sku, 0.99, "matched a saved alias", as_candidates([product], {product.sku: 100}))

    candidates = catalogue
    missing = []

    # 2. Filter by hard attributes. Each must agree, or the SKU is out.
    brand = row.get("brand")
    if brand:
        candidates = [p for p in candidates if max(similarity(brand, b) for b in [p.brand, *p.brand_aliases]) >= BRAND_MATCH_AT]
    else:
        missing.append("brand")
    brand_matches = candidates  # kept for "closest products" when nothing fits

    size_ml = volume_to_ml(str(row.get("size") or ""))
    if size_ml:
        candidates = [p for p in candidates if p.size_ml == size_ml]
    else:
        missing.append("size")

    pack_type = pack_type_of(row.get("pack_type")) or pack_type_of(row.get("product_text"))
    if pack_type:
        candidates = [p for p in candidates if p.pack_type == pack_type]
    else:
        missing.append("pack type")

    pack_count = row.get("pack_count")
    if pack_count:
        candidates = [p for p in candidates if p.pack_count == int(pack_count)]
    else:
        missing.append("pack count")

    # 3. Rank what is left by flavour: spelling first (fuzzy), meaning second (embeddings)
    flavour = row.get("flavour")
    scores = {p.sku: similarity(flavour, p.type) if flavour else 50.0 for p in candidates}
    before_flavour = candidates
    if flavour:
        candidates = [p for p in candidates if scores[p.sku] >= FLAVOUR_MATCH_AT]
        if not spelling_decides(candidates, scores):
            by_meaning = match_by_meaning(row, before_flavour, meaning)
            if by_meaning:
                return by_meaning
    else:
        missing.append("flavour")

    # 4. Decide
    if not candidates:
        near = {p.sku: similarity(alias, p.name) for p in brand_matches}
        return Match(None, 0.0, "no catalogue product matches these attributes", as_candidates(brand_matches, near))

    ranked = sorted(candidates, key=lambda p: scores[p.sku], reverse=True)
    if len(ranked) > 1:
        gap = scores[ranked[0].sku] - scores[ranked[1].sku]
        if not (flavour and gap >= CLEAR_WINNER_GAP):
            why = f"{', '.join(missing)} missing; " if missing else ""
            return Match(None, 0.0, f"{why}{len(ranked)} SKUs fit", as_candidates(ranked, scores))

    best = ranked[0]
    # attributes that were missing but did not matter (only one SKU had them anyway)
    confidence = round(1.0 - UNUSED_MISSING_PENALTY * len(missing), 2)
    reason = "one SKU fits" + (f" ({', '.join(missing)} not shown)" if missing else "")
    return Match(best.sku, confidence, reason, as_candidates(ranked, scores))


def spelling_decides(shortlist: list[Product], scores: dict[str, float]) -> bool:
    """True when fuzzy matching already settled the flavour (meaning can't help with a missing size)."""
    if len({p.type for p in shortlist}) == 1:
        return True
    if len(shortlist) > 1:
        ranked = sorted((scores[p.sku] for p in shortlist), reverse=True)
        return ranked[0] - ranked[1] >= CLEAR_WINNER_GAP
    return False


def unit_price(row: dict, product: Product | None) -> float | None:
    price = row.get("price")
    if price is None:
        return None
    count = product.pack_count if product else int(row.get("pack_count") or 1)
    basis = (row.get("price_basis") or "").lower()
    if count > 1 and "each" not in basis:
        return round(price / count, 2)
    return price


def match_products(
    data: dict,
    template: Template,
    catalogue: list[Product],
    lines: list[Line] | None = None,
    meaning: MeaningFn | None = None,
) -> list[FieldResult]:
    """One extra FieldResult per product row: '<table>[i].sku'."""
    if not template.product_table:
        return []
    table_key = to_key(template.product_table)
    by_sku = {p.sku: p for p in catalogue}
    results = []

    for i, row in enumerate(data.get(table_key) or []):
        match = match_row(row, catalogue, meaning)
        product = by_sku.get(match.sku) if match.sku else None
        result = FieldResult(
            name=f"{table_key}[{i}].sku",
            value=match.sku,
            normalized_value={"product": product.name if product else None, "unit_price": unit_price(row, product)},
            confidence=match.confidence,
            issues=[match.reason],
            candidate_skus=match.candidates,
        )
        result.status = "auto_approved" if match.sku and match.confidence >= AUTO_APPROVE_AT else "needs_review"
        line = locate(row.get("product_text") or row.get("brand"), lines or [])
        if line:
            result.page, result.bbox = line.page, line.bbox
        results.append(result)

    return results
