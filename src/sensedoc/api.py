"""The REST API. It only accepts uploads and queues jobs, so slow LLM calls never block users.

Run it:  uv run uvicorn sensedoc.api:app --reload
Docs:    http://localhost:8000/docs
"""

import hashlib
import json
import os
import statistics
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pymupdf
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sensedoc import config
from sensedoc.db import (
    DocumentRow,
    ExtractedValueRow,
    ExtractionRunRow,
    ProductRow,
    ReviewRow,
    SessionLocal,
    TemplateFieldRow,
    TemplateRow,
    latest_templates,
    save_template,
    template_from_row,
)
from sensedoc.export import export_rows, to_file
from sensedoc.pipeline import import_catalogue_csv, row_alias_for, seed, storage_path_for
from sensedoc.readers import IMAGE_TYPES
from sensedoc.schema_builder import Template
from sensedoc.worker import enqueue

SUPPORTED = {".pdf", ".xlsx", ".csv", ".docx", *IMAGE_TYPES}
LANDING_PAGE = config.PROJECT_ROOT / "web" / "index.html"
UI_URL = os.getenv("UI_URL", "http://localhost:8501")
EVAL_RESULTS = config.PROJECT_ROOT / "evaluation" / "results.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="SenseDoc API", version="0.1.0", lifespan=lifespan)


def get_db():
    with SessionLocal() as db:
        yield db


# ---------- Landing page ----------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing() -> str:
    return LANDING_PAGE.read_text()


@app.get("/app", include_in_schema=False)
def open_app() -> RedirectResponse:
    return RedirectResponse(UI_URL)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------- Templates ----------
def template_out(row: TemplateRow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "document_type": row.document_type,
        "version": row.version,
        "created_at": row.created_at,
        "template": template_from_row(row).model_dump(),
    }


@app.post("/templates", status_code=201)
def create_template(template: Template, db: Session = Depends(get_db)) -> dict:
    row = save_template(db, template)
    db.commit()
    return template_out(row)


@app.get("/templates")
def list_templates(db: Session = Depends(get_db)) -> list[dict]:
    return [template_out(r) for r in latest_templates(db)]


@app.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    return template_out(get_or_404(db, TemplateRow, template_id))


@app.put("/templates/{template_id}")
def edit_template(template_id: int, template: Template, db: Session = Depends(get_db)) -> dict:
    """Editing never changes old results: it saves a new version."""
    old = get_or_404(db, TemplateRow, template_id)
    newest = db.scalar(select(func.max(TemplateRow.version)).where(TemplateRow.name == old.name))
    row = save_template(db, template.model_copy(update={"name": old.name}), version=newest + 1)
    db.commit()
    return template_out(row)


# ---------- Documents ----------
def document_out(doc: DocumentRow, with_values: bool = False) -> dict:
    run = doc.runs[-1] if doc.runs else None
    out = {
        "id": doc.id,
        "template_id": doc.template_id,
        "template_name": doc.template.name,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "page_count": doc.page_count,
        "status": doc.status,
        "error": doc.error,
        "uploaded_at": doc.uploaded_at,
        "run": None,
    }
    if run:
        out["run"] = {
            "id": run.id,
            "model": run.model,
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
            "cost_usd": run.cost_usd,
            "latency_ms": run.latency_ms,
            "attempts": run.attempts,
        }
        if with_values:
            out["values"] = [value_out(v) for v in run.values]
    return out


def value_out(v: ExtractedValueRow) -> dict:
    return {
        "id": v.id,
        "field_path": v.field_path,
        "value": v.value,
        "normalized_value": v.normalized_value,
        "confidence": v.confidence,
        "status": v.status,
        "issues": v.issues,
        "matched_sku": v.matched_sku,
        "candidate_skus": v.candidate_skus,
    }


@app.post("/documents", status_code=202)
async def upload_documents(
    background_tasks: BackgroundTasks,
    template_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> list[dict]:
    get_or_404(db, TemplateRow, template_id)
    created = []
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(415, f"{upload.filename}: unsupported file type {suffix}")
        data = await upload.read()
        if len(data) > config.MAX_FILE_MB * 1024 * 1024:
            raise HTTPException(413, f"{upload.filename}: larger than {config.MAX_FILE_MB} MB")

        path = storage_path_for(f"{uuid.uuid4().hex}{suffix}")
        path.write_bytes(data)
        doc = DocumentRow(
            template_id=template_id,
            filename=upload.filename,
            file_type=suffix.lstrip("."),
            storage_path=str(path),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        db.add(doc)
        db.commit()
        created.append(doc)

    for doc in created:
        enqueue(doc.id, background_tasks)
    return [{"id": d.id, "filename": d.filename, "status": d.status} for d in created]


@app.get("/documents")
def list_documents(template_id: int | None = None, status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    query = select(DocumentRow).order_by(DocumentRow.id.desc())
    if template_id:
        query = query.where(DocumentRow.template_id == template_id)
    if status:
        query = query.where(DocumentRow.status == status)
    return [document_out(d) for d in db.scalars(query).all()]


@app.get("/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    return document_out(get_or_404(db, DocumentRow, document_id), with_values=True)


@app.get("/documents/{document_id}/file")
def get_document_file(document_id: int, db: Session = Depends(get_db)) -> FileResponse:
    doc = get_or_404(db, DocumentRow, document_id)
    return FileResponse(doc.storage_path, filename=doc.filename)


@app.get("/documents/{document_id}/preview")
def preview(document_id: int, page: int = 1, db: Session = Depends(get_db)) -> Response:
    """A PNG of one page, shown next to the values in the review screen."""
    doc = get_or_404(db, DocumentRow, document_id)
    suffix = "." + doc.file_type
    if suffix in IMAGE_TYPES:
        return FileResponse(doc.storage_path, media_type=IMAGE_TYPES[suffix])
    if suffix == ".pdf":
        with pymupdf.open(doc.storage_path) as pdf:
            if not 1 <= page <= len(pdf):
                raise HTTPException(404, "no such page")
            return Response(pdf[page - 1].get_pixmap(dpi=110).tobytes("png"), media_type="image/png")
    raise HTTPException(404, "no preview for this file type")


@app.post("/documents/{document_id}/reprocess", status_code=202)
def reprocess(document_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    doc = get_or_404(db, DocumentRow, document_id)
    doc.status = "queued"
    db.commit()
    enqueue(doc.id, background_tasks)
    return {"id": doc.id, "status": doc.status}


# ---------- Review ----------
@app.get("/review-queue")
def review_queue(limit: int = 200, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(ExtractedValueRow, DocumentRow)
        .join(ExtractionRunRow, ExtractedValueRow.run_id == ExtractionRunRow.id)
        .join(DocumentRow, ExtractionRunRow.document_id == DocumentRow.id)
        .where(ExtractedValueRow.status == "needs_review")
        .order_by(DocumentRow.uploaded_at, ExtractedValueRow.id)
        .limit(limit)
    ).all()
    return [{**value_out(v), "document_id": d.id, "filename": d.filename} for v, d in rows]


class ReviewIn(BaseModel):
    action: Literal["approve", "correct"]
    new_value: Any = None
    reviewer: str = "reviewer"


def convert(value: Any, field_type: str | None) -> Any:
    """Reviewers type text; store it with the field's real type."""
    if value in (None, ""):
        return None
    if field_type in ("number", "currency"):
        return float(str(value).replace(",", ""))
    if field_type == "date":
        return date.fromisoformat(str(value)).isoformat()
    return value


@app.patch("/values/{value_id}")
def review_value(value_id: int, review: ReviewIn, db: Session = Depends(get_db)) -> dict:
    value = get_or_404(db, ExtractedValueRow, value_id)
    old = value.value

    if review.action == "approve":
        value.status = "approved"
    else:
        field = db.get(TemplateFieldRow, value.field_id) if value.field_id else None
        try:
            new = convert(review.new_value, field.type if field else None)
        except ValueError as e:
            raise HTTPException(422, f"not a valid value: {e}")
        value.value, value.status = new, "corrected"
        if value.matched_sku is not None or value.candidate_skus is not None:
            learn_alias(db, value, new)

    db.add(ReviewRow(value_id=value.id, old_value=old, new_value=value.value, reviewer=review.reviewer))

    # the document is done once nothing in its latest run waits for review
    doc = value.run.document
    if not any(v.status == "needs_review" for v in doc.runs[-1].values):
        doc.status = "done"
    db.commit()
    return value_out(value)


def learn_alias(db: Session, value: ExtractedValueRow, sku: str | None) -> None:
    """Remember the reviewer's choice: this wording means this SKU from now on."""
    product = db.get(ProductRow, sku) if sku else None
    if not product:
        raise HTTPException(422, f"unknown SKU {sku!r}")
    value.matched_sku, value.match_confidence = sku, 1.0
    alias = row_alias_for(value)
    if alias and alias not in (product.aliases or []):
        product.aliases = [*(product.aliases or []), alias]


# ---------- Export ----------
@app.get("/templates/{template_id}/export")
def export(
    template_id: int,
    format: Literal["csv", "xlsx", "json"] = "csv",
    include_unreviewed: bool = False,
    db: Session = Depends(get_db),
) -> Response:
    template = get_or_404(db, TemplateRow, template_id)
    content, media_type = to_file(export_rows(db, template, include_unreviewed), format)
    filename = f"{template.name.lower().replace(' ', '_')}.{format}"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------- Catalogue ----------
@app.get("/products")
def list_products(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {c: getattr(p, c) for c in ("sku", "brand", "type", "size_ml", "pack_type", "pack_count", "brand_aliases", "aliases")}
        for p in db.scalars(select(ProductRow).order_by(ProductRow.sku)).all()
    ]


@app.post("/products/import")
async def import_products(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    return {"imported": import_catalogue_csv(db, (await file.read()).decode())}


# ---------- Metrics ----------
@app.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict:
    doc_counts = dict(db.execute(select(DocumentRow.status, func.count()).group_by(DocumentRow.status)).all())
    value_counts = dict(
        db.execute(
            select(ExtractedValueRow.status, func.count())
            .where(ExtractedValueRow.status != "superseded")
            .group_by(ExtractedValueRow.status)
        ).all()
    )
    runs = db.scalars(select(ExtractionRunRow)).all()
    pages = sum(r.document.page_count or 1 for r in runs)
    total_values = sum(value_counts.values())
    reviewed = value_counts.get("approved", 0) + value_counts.get("corrected", 0)

    return {
        "documents": doc_counts,
        "values": value_counts,
        "auto_approved_rate": round(value_counts.get("auto_approved", 0) / total_values, 3) if total_values else None,
        # of the values a human checked, how many were already right
        "reviewer_agreement": round(value_counts.get("approved", 0) / reviewed, 3) if reviewed else None,
        "median_latency_ms": statistics.median(r.latency_ms for r in runs) if runs else None,
        "tokens_in": sum(r.tokens_in for r in runs),
        "tokens_out": sum(r.tokens_out for r in runs),
        "cost_usd": round(sum(r.cost_usd for r in runs), 4),
        "cost_per_1000_pages_usd": round(sum(r.cost_usd for r in runs) / pages * 1000, 2) if pages else None,
        "models": dict(db.execute(select(ExtractionRunRow.model, func.count()).group_by(ExtractionRunRow.model)).all()),
        "evaluation": json.loads(EVAL_RESULTS.read_text()) if EVAL_RESULTS.exists() else None,
    }


def get_or_404(db: Session, model, key):
    row = db.get(model, key)
    if row is None:
        raise HTTPException(404, f"{model.__tablename__[:-1]} {key} not found")
    return row
