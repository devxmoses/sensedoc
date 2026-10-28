"""Check extracted values and give each one a confidence score."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel

from sensedoc.normalize import NORMALIZERS
from sensedoc.ocr import Line
from sensedoc.readers import ParsedDocument
from sensedoc.schema_builder import Rule, Template, TemplateField, to_key

AUTO_APPROVE_AT = 0.8  # values scoring at least this skip human review
IMAGE_ONLY_CONFIDENCE = 0.85  # read from a picture: nothing to cross-check against
NOT_IN_TEXT_PENALTY = 0.4
RULE_FAILED_PENALTY = 0.3
NORMALIZE_FAILED_PENALTY = 0.3


@dataclass
class FieldResult:
    name: str  # e.g. "total_amount" or "items[2].unit_price"
    value: Any
    normalized_value: Any = None
    confidence: float = 1.0
    status: str = "auto_approved"  # or "needs_review"
    issues: list[str] = field(default_factory=list)
    candidate_skus: list[dict] | None = None  # only for product-match rows
    page: int | None = None  # where the value was found, for source highlighting
    bbox: tuple[float, float, float, float] | None = None

    def flag(self, issue: str, penalty: float) -> None:
        self.issues.append(issue)
        self.confidence = max(0.0, self.confidence - penalty)


# ---------- Is the value really in the document? ----------
def squash(text: str) -> str:
    """Lowercase, drop thousands commas, collapse spaces: '12,000.00 ' -> '12000.00'"""
    return " ".join(text.replace(",", "").split()).lower()


def written_forms(value: Any) -> list[str]:
    """The ways a value might be printed on a page."""
    if isinstance(value, date):
        forms = [value.isoformat()]
        for day in (value.strftime("%d"), str(value.day)):
            forms += [
                f"{day} {value:%B %Y}",  # 14 October 2026
                f"{day} {value:%b %Y}",  # 14 Oct 2026
                f"{day}/{value:%m/%Y}",  # 14/10/2026
                f"{value:%B} {day} {value:%Y}",  # October 14 2026
            ]
        return forms
    if isinstance(value, float):
        forms = [f"{value:.2f}"]
        if value.is_integer():
            forms.append(str(int(value)))
        return forms
    return [str(value)]


def in_text(value: Any, text: str) -> bool:
    if isinstance(value, list):
        return all(in_text(item, text) for item in value)
    page = squash(text)
    return any(squash(form) in page for form in written_forms(value))


def locate(value: Any, lines: list[Line]) -> Line | None:
    """The line where a value is printed. With several matches, the shortest line is the tightest fit."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None or not lines:
        return None
    forms = [f for f in (squash(form) for form in written_forms(value)) if f]
    matches = [line for line in lines if any(f in squash(line.text) for f in forms)]
    return min(matches, key=lambda line: len(line.text), default=None)


# ---------- Checks on a single value ----------
def check_value(name: str, value: Any, template_field: TemplateField, doc: ParsedDocument) -> FieldResult:
    result = FieldResult(name=name, value=value)

    if value is None or value == []:
        if template_field.required:
            result.flag("required field is missing", 1.0)
        return result

    if doc.text and in_text(value, doc.text):
        pass  # found it written in the document: keep full confidence
    elif doc.images and doc.ocr_text and in_text(value, doc.ocr_text):
        pass  # read from a picture, and OCR read the same thing independently
    elif doc.images:
        result.confidence = IMAGE_ONLY_CONFIDENCE
        result.issues.append("read from an image, not confirmed by OCR")
    else:
        result.flag("value not found in the document text", NOT_IN_TEXT_PENALTY)

    line = locate(value, doc.lines)
    if line:
        result.page, result.bbox = line.page, line.bbox

    if template_field.normalize:
        result.normalized_value = NORMALIZERS[template_field.normalize](str(value))
        if result.normalized_value is None:
            result.flag(f"could not convert to {template_field.normalize}", NORMALIZE_FAILED_PENALTY)

    return result


# ---------- Checks across several values ----------
def apply_rule(rule: Rule, data: dict, by_name: dict[str, FieldResult]) -> None:
    target_key = to_key(rule.target)
    target = data.get(target_key)

    if rule.type == "table_sum":
        table_key, column_key = to_key(rule.table), to_key(rule.column)
        rows = data.get(table_key) or []
        parts = [row.get(column_key) for row in rows]
        involved = [f"{table_key}[{i}].{column_key}" for i in range(len(rows))]
        label = f"{rule.table} {rule.column}"
    else:  # fields_sum
        involved = [to_key(name) for name in rule.fields]
        parts = [data.get(key) for key in involved]
        label = " + ".join(rule.fields)

    if target is None or not parts or None in parts:
        return  # can't check; missing values are flagged elsewhere

    total = sum(parts)
    if abs(total - target) > rule.tolerance:
        issue = f"{label} adds up to {total:,.2f}, but {rule.target} is {target:,.2f}"
        for name in [target_key, *involved]:
            if name in by_name:
                by_name[name].flag(issue, RULE_FAILED_PENALTY)


# ---------- Run everything ----------
def validate(result: BaseModel, template: Template, doc: ParsedDocument) -> list[FieldResult]:
    data = result.model_dump()
    results: list[FieldResult] = []

    for template_field in template.fields:
        key = to_key(template_field.name)
        value = data.get(key)

        if template_field.type == "table" and value:
            # one result per cell, so each one can be reviewed on its own
            for i, row in enumerate(value):
                for column in template_field.columns:
                    column_key = to_key(column.name)
                    results.append(check_value(f"{key}[{i}].{column_key}", row.get(column_key), column, doc))
        else:
            results.append(check_value(key, value, template_field, doc))

    by_name = {r.name: r for r in results}
    for rule in template.rules:
        apply_rule(rule, data, by_name)

    set_statuses(results)
    return results


def set_statuses(results: list[FieldResult]) -> None:
    for r in results:
        r.status = "auto_approved" if r.confidence >= AUTO_APPROVE_AT else "needs_review"


def document_status(results: list[FieldResult]) -> str:
    return "needs_review" if any(r.status == "needs_review" for r in results) else "done"
