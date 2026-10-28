"""Turn uploaded files into text and/or images the LLM can read."""

from dataclasses import dataclass, field
from pathlib import Path

import docx
import pandas as pd
import pymupdf

MIN_TEXT_CHARS = 50  # a PDF page with less text than this is probably a scan

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass
class Image:
    data: bytes
    mime_type: str


@dataclass
class ParsedDocument:
    text: str = ""
    images: list[Image] = field(default_factory=list)
    page_count: int = 1


def read_pdf(path: Path) -> ParsedDocument:
    parsed = ParsedDocument()
    texts = []
    with pymupdf.open(path) as pdf:
        parsed.page_count = len(pdf)
        for number, page in enumerate(pdf, start=1):
            page_text = page.get_text().strip()
            if len(page_text) >= MIN_TEXT_CHARS:
                texts.append(f"--- Page {number} ---\n{page_text}")
            else:
                # no real text: probably a scan, so send a picture of the page
                pixmap = page.get_pixmap(dpi=200)
                parsed.images.append(Image(pixmap.tobytes("png"), "image/png"))
    parsed.text = "\n\n".join(texts)
    return parsed


def read_image(path: Path) -> ParsedDocument:
    mime_type = IMAGE_TYPES[path.suffix.lower()]
    return ParsedDocument(images=[Image(path.read_bytes(), mime_type)])


def read_spreadsheet(path: Path) -> ParsedDocument:
    if path.suffix.lower() == ".csv":
        sheets = {"Sheet1": pd.read_csv(path)}
    else:
        sheets = pd.read_excel(path, sheet_name=None)  # None means "every sheet"
    parts = [f"--- Sheet: {name} ---\n{df.to_csv(index=False)}" for name, df in sheets.items()]
    return ParsedDocument(text="\n\n".join(parts))


def read_docx(path: Path) -> ParsedDocument:
    document = docx.Document(path)
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return ParsedDocument(text="\n".join(parts))


def read_document(path: str | Path) -> ParsedDocument:
    """Pick the right reader based on the file extension."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return read_pdf(path)
    if suffix in IMAGE_TYPES:
        return read_image(path)
    if suffix in (".xlsx", ".csv"):
        return read_spreadsheet(path)
    if suffix == ".docx":
        return read_docx(path)

    raise ValueError(f"Unsupported file type: {suffix}")
