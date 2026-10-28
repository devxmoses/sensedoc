"""Turn approved values into flat rows for CSV, Excel and JSON."""

import io
import re

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from sensedoc.db import DocumentRow, TemplateRow
from sensedoc.schema_builder import to_key

EXPORTABLE = {"auto_approved", "approved", "corrected"}
CELL = re.compile(r"^(\w+)\[(\d+)\]\.(\w+)$")  # items[2].unit_price


def document_values(doc: DocumentRow) -> tuple[dict, dict[str, dict[int, dict]]]:
    """Latest run -> ({field: value}, {table: {row_index: {column: value}}})."""
    fields, tables = {}, {}
    if not doc.runs:
        return fields, tables
    for v in doc.runs[-1].values:
        if v.status not in EXPORTABLE:
            continue
        cell = CELL.match(v.field_path)
        if cell:
            table, index, column = cell.groups()
            row = tables.setdefault(table, {}).setdefault(int(index), {})
            row[column] = v.value
            if column == "sku" and isinstance(v.normalized_value, dict):
                row["sku_name"] = v.normalized_value.get("product")
                row["unit_price"] = v.normalized_value.get("unit_price")
        else:
            fields[v.field_path] = v.value
    return fields, tables


def export_rows(db: Session, template: TemplateRow, include_unreviewed: bool = False) -> list[dict]:
    """One row per table row (header fields repeated), or one row per document if there is no table."""
    statuses = {"done", "needs_review"} if include_unreviewed else {"done"}
    docs = db.scalars(
        select(DocumentRow).where(DocumentRow.template_id == template.id, DocumentRow.status.in_(statuses))
    ).all()
    main_table = to_key(template.product_table) if template.product_table else next(
        (to_key(f.name) for f in template.fields if f.type == "table" and f.parent_id is None), None
    )

    rows = []
    for doc in docs:
        fields, tables = document_values(doc)
        base = {"document_id": doc.id, "filename": doc.filename, **fields}
        table_rows = tables.get(main_table, {}) if main_table else {}
        if table_rows:
            for index in sorted(table_rows):
                rows.append({**base, "row": index + 1, **table_rows[index]})
        else:
            rows.append(base)
    return rows


def to_file(rows: list[dict], fmt: str) -> tuple[bytes, str]:
    df = pd.DataFrame(rows)
    if fmt == "csv":
        return df.to_csv(index=False).encode(), "text/csv"
    if fmt == "xlsx":
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, sheet_name="SenseDoc")
        return buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return df.to_json(orient="records", indent=2, date_format="iso").encode(), "application/json"
