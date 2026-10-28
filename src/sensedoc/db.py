"""Database tables (the plan's data model) and helpers to move templates in and out."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from sensedoc import config
from sensedoc.schema_builder import Rule, Template, TemplateField, to_key

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TemplateRow(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    document_type: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(default=1)
    rules: Mapped[list[Any]] = mapped_column(default=list)
    product_table: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)
    fields: Mapped[list["TemplateFieldRow"]] = relationship(
        back_populates="template", cascade="all, delete-orphan", order_by="TemplateFieldRow.position"
    )


class TemplateFieldRow(Base):
    __tablename__ = "template_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("template_fields.id"))  # set for table columns
    position: Mapped[int] = mapped_column(default=0)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    required: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list[Any]] = mapped_column(default=list)
    validation_rules: Mapped[dict[str, Any]] = mapped_column(default=dict)
    template: Mapped[TemplateRow] = relationship(back_populates="fields")


class DocumentRow(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(20))
    storage_path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued/processing/needs_review/done/failed
    error: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(default=now)
    template: Mapped[TemplateRow] = relationship()
    runs: Mapped[list["ExtractionRunRow"]] = relationship(back_populates="document", order_by="ExtractionRunRow.id")


class ExtractionRunRow(Base):
    __tablename__ = "extraction_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=now)
    document: Mapped[DocumentRow] = relationship(back_populates="runs")
    values: Mapped[list["ExtractedValueRow"]] = relationship(back_populates="run", order_by="ExtractedValueRow.id")


class ExtractedValueRow(Base):
    __tablename__ = "extracted_values"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("extraction_runs.id"))
    field_id: Mapped[int | None] = mapped_column(ForeignKey("template_fields.id"))
    field_path: Mapped[str] = mapped_column(String(300))  # e.g. "items[2].unit_price"
    value: Mapped[Any | None] = mapped_column(JSON)
    normalized_value: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    page: Mapped[int | None]
    bbox: Mapped[Any | None] = mapped_column(JSON)  # filled once OCR word boxes exist (Step 8b)
    status: Mapped[str] = mapped_column(String(20))  # auto_approved/needs_review/corrected/approved/superseded
    issues: Mapped[list[Any]] = mapped_column(default=list)
    matched_sku: Mapped[str | None] = mapped_column(String(100))
    match_confidence: Mapped[float | None] = mapped_column(Float)
    candidate_skus: Mapped[Any | None] = mapped_column(JSON)
    run: Mapped[ExtractionRunRow] = relationship(back_populates="values")


class ReviewRow(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    value_id: Mapped[int] = mapped_column(ForeignKey("extracted_values.id"))
    old_value: Mapped[Any | None] = mapped_column(JSON)
    new_value: Mapped[Any | None] = mapped_column(JSON)
    reviewer: Mapped[str] = mapped_column(String(200))
    reviewed_at: Mapped[datetime] = mapped_column(default=now)


class ProductRow(Base):
    __tablename__ = "products"
    sku: Mapped[str] = mapped_column(String(100), primary_key=True)
    brand: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(200))
    size_ml: Mapped[float] = mapped_column(Float)
    pack_type: Mapped[str] = mapped_column(String(20))
    pack_count: Mapped[int] = mapped_column(default=1)
    brand_aliases: Mapped[list[Any]] = mapped_column(default=list)
    aliases: Mapped[list[Any]] = mapped_column(default=list)  # learned from reviewer corrections


def create_tables() -> None:
    Base.metadata.create_all(engine)


# ---------- Template <-> database ----------
def field_to_row(field: TemplateField, position: int) -> TemplateFieldRow:
    return TemplateFieldRow(
        position=position,
        name=field.name,
        type=field.type,
        required=field.required,
        description=field.description,
        examples=field.examples,
        validation_rules={"normalize": field.normalize} if field.normalize else {},
    )


def save_template(db: Session, template: Template, version: int = 1) -> TemplateRow:
    row = TemplateRow(
        name=template.name,
        document_type=template.document_type,
        version=version,
        rules=[r.model_dump() for r in template.rules],
        product_table=template.product_table,
    )
    db.add(row)
    for i, field in enumerate(template.fields):
        parent = field_to_row(field, i)
        row.fields.append(parent)
        if field.columns:
            db.flush()  # writes the parent so it gets an id
            for j, column in enumerate(field.columns):
                child = field_to_row(column, j)
                child.parent_id = parent.id
                row.fields.append(child)
    db.flush()
    return row


def template_from_row(row: TemplateRow) -> Template:
    def to_field(f: TemplateFieldRow) -> TemplateField:
        columns = [to_field(c) for c in row.fields if c.parent_id == f.id]
        return TemplateField(
            name=f.name,
            type=f.type,
            required=f.required,
            description=f.description,
            examples=f.examples or [],
            columns=columns,
            normalize=(f.validation_rules or {}).get("normalize"),
        )

    return Template(
        name=row.name,
        document_type=row.document_type,
        fields=[to_field(f) for f in row.fields if f.parent_id is None],
        rules=[Rule(**r) for r in row.rules or []],
        product_table=row.product_table,
    )


def field_ids_by_path(row: TemplateRow) -> dict[str, int]:
    """'invoice_number' -> id, 'items.line_total' -> id (row index removed)."""
    parents = {f.id: f for f in row.fields}
    ids = {}
    for f in row.fields:
        if f.parent_id is None:
            ids[to_key(f.name)] = f.id
        else:
            ids[f"{to_key(parents[f.parent_id].name)}.{to_key(f.name)}"] = f.id
    return ids


def latest_templates(db: Session) -> list[TemplateRow]:
    rows = db.scalars(select(TemplateRow).order_by(TemplateRow.name, TemplateRow.version.desc())).all()
    latest = {}
    for r in rows:
        latest.setdefault(r.name, r)
    return sorted(latest.values(), key=lambda r: r.id)
