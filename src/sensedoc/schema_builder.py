"""Turn a user-defined template into a Pydantic model at runtime."""

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

FieldType = Literal["text", "number", "date", "currency", "list", "table"]


class TemplateField(BaseModel):
    name: str
    type: FieldType = "text"
    required: bool = False
    description: str = ""
    examples: list[str] = []
    columns: list["TemplateField"] = []  # only used when type is "table"
    normalize: Literal["volume_ml"] | None = None  # optional clean-up step


class Rule(BaseModel):
    """A cross-field check, e.g. 'the line totals must add up to the subtotal'."""

    type: Literal["table_sum", "fields_sum"]
    target: str  # the field that should equal the sum
    table: str | None = None  # table_sum: which table
    column: str | None = None  # table_sum: which column to add up
    fields: list[str] = []  # fields_sum: which fields to add up
    tolerance: float = 0.01  # allow tiny rounding differences


class Template(BaseModel):
    name: str
    document_type: str
    fields: list[TemplateField]
    rules: list[Rule] = []
    product_table: str | None = None  # table whose rows are matched to the SKU catalogue


# ---------- Template type → Python type ----------
SIMPLE_TYPES: dict[str, Any] = {
    "text": str,
    "number": float,
    "date": date,
    "currency": float,
    "list": list[str],
}


def to_key(name: str) -> str:
    """'Invoice Number' -> 'invoice_number'"""
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not key or key[0].isdigit():
        key = "f_" + key
    return key


def describe(field: TemplateField) -> str:
    """The text the LLM reads about this field."""
    text = field.description
    if field.examples:
        text += f" Examples: {', '.join(field.examples)}."
    return text.strip()


def build_model(name: str, fields: list[TemplateField]) -> type[BaseModel]:
    definitions: dict[str, Any] = {}

    for field in fields:
        if field.type == "table":
            # a table is a list of rows; each row is its own small model
            row_model = build_model(f"{name}_{to_key(field.name)}_row", field.columns)
            python_type = list[row_model]
        else:
            python_type = SIMPLE_TYPES[field.type]

        definitions[to_key(field.name)] = (
            python_type | None,
            Field(None, description=describe(field)),
        )

    return create_model(name, **definitions)
