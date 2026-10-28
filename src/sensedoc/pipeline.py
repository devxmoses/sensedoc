"""The whole journey of one document: read -> extract -> validate -> match -> save."""

import csv
import re
from pathlib import Path

from pydantic_core import to_jsonable_python
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sensedoc import config
from sensedoc.db import (
    DocumentRow,
    ExtractedValueRow,
    ExtractionRunRow,
    ProductRow,
    SessionLocal,
    TemplateRow,
    create_tables,
    field_ids_by_path,
    save_template,
    template_from_row,
)
from sensedoc.extractor import PROMPT_VERSION, extract
from sensedoc.matching import Product, match_products, row_alias
from sensedoc.readers import read_document
from sensedoc.validator import document_status, validate

PAGE_IN_PATH = re.compile(r"\[\d+\]")


def load_catalogue(db: Session) -> list[Product]:
    return [
        Product(
            sku=p.sku,
            brand=p.brand,
            type=p.type,
            size_ml=p.size_ml,
            pack_type=p.pack_type,
            pack_count=p.pack_count,
            brand_aliases=p.brand_aliases or [],
            aliases=p.aliases or [],
        )
        for p in db.scalars(select(ProductRow)).all()
    ]


def import_catalogue_csv(db: Session, text: str) -> int:
    """CSV columns: sku, brand, type, size_ml, pack_type, pack_count, brand_aliases (';'-separated)."""
    count = 0
    for r in csv.DictReader(text.splitlines()):
        product = db.get(ProductRow, r["sku"]) or ProductRow(sku=r["sku"], aliases=[])
        product.brand = r["brand"]
        product.type = r["type"]
        product.size_ml = float(r["size_ml"])
        product.pack_type = r["pack_type"].lower()
        product.pack_count = int(r.get("pack_count") or 1)
        product.brand_aliases = [a.strip() for a in (r.get("brand_aliases") or "").split(";") if a.strip()]
        db.add(product)
        count += 1
    db.commit()
    return count


def process_document(document_id: int) -> str:
    """Run the pipeline for one document and return its final status."""
    with SessionLocal() as db:
        doc = db.get(DocumentRow, document_id)
        doc.status, doc.error = "processing", None
        db.commit()

        template = template_from_row(doc.template)
        try:
            parsed = read_document(doc.storage_path)
            doc.page_count = parsed.page_count
            if parsed.page_count > config.MAX_PAGES:
                raise ValueError(f"{parsed.page_count} pages; the limit is {config.MAX_PAGES}")
            output = extract(parsed, template)
        except Exception as e:  # never crash the job: record why and move on
            doc.status, doc.error = "failed", f"{type(e).__name__}: {e}"[:2000]
            db.commit()
            return doc.status

        results = validate(output.data, template, parsed)
        results += match_products(output.data.model_dump(), template, load_catalogue(db))

        # older runs of this document no longer count
        old_runs = [r.id for r in doc.runs]
        if old_runs:
            db.execute(
                update(ExtractedValueRow).where(ExtractedValueRow.run_id.in_(old_runs)).values(status="superseded")
            )

        run = ExtractionRunRow(
            document_id=doc.id,
            model=output.model,
            prompt_version=PROMPT_VERSION,
            tokens_in=output.tokens_in,
            tokens_out=output.tokens_out,
            cost_usd=output.cost_usd,
            latency_ms=output.latency_ms,
            attempts=output.attempts,
        )
        db.add(run)
        field_ids = field_ids_by_path(doc.template)
        for r in results:
            is_sku = r.candidate_skus is not None
            run.values.append(
                ExtractedValueRow(
                    field_id=field_ids.get(PAGE_IN_PATH.sub("", r.name)),
                    field_path=r.name,
                    value=to_jsonable_python(r.value),
                    normalized_value=to_jsonable_python(r.normalized_value),
                    confidence=r.confidence,
                    status=r.status,
                    issues=r.issues,
                    matched_sku=r.value if is_sku else None,
                    match_confidence=r.confidence if is_sku else None,
                    candidate_skus=r.candidate_skus,
                )
            )

        doc.status = document_status(results)
        db.commit()
        return doc.status


def seed(db: Session) -> None:
    """First start: create tables, load the ready-made templates and the sample catalogue."""
    create_tables()
    if not db.scalars(select(TemplateRow)).first():
        from sensedoc.schema_builder import Template

        for path in sorted((config.PROJECT_ROOT / "templates").glob("*.json")):
            save_template(db, Template.model_validate_json(path.read_text()))
        db.commit()
    catalogue = config.PROJECT_ROOT / "samples" / "catalogue.csv"
    if not db.scalars(select(ProductRow)).first() and catalogue.exists():
        import_catalogue_csv(db, catalogue.read_text())


def storage_path_for(name: str) -> Path:
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return config.STORAGE_DIR / name


def row_alias_for(sku_value: ExtractedValueRow) -> str:
    """Rebuild the product row behind a '<table>[i].sku' value and return its alias text."""
    prefix = sku_value.field_path.removesuffix("sku")  # "products[3]."
    row = {
        v.field_path.removeprefix(prefix): v.value
        for v in sku_value.run.values
        if v.field_path.startswith(prefix) and v.id != sku_value.id
    }
    return row_alias(row)
