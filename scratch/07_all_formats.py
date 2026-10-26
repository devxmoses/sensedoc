from pathlib import Path

from sensedoc.extractor import extract
from sensedoc.readers import read_document
from sensedoc.schema_builder import Template

template = Template.model_validate_json(Path("templates/invoice.json").read_text())

files = [
    "samples/invoice_001.pdf",
    "samples/invoice_001_scanned.pdf",
    "samples/invoice_001_photo.png",
    "samples/invoice_002.docx",
]

for path in files:
    doc = read_document(path)
    print(f"\n===== {path} =====")
    print(f"text: {len(doc.text)} characters | images: {len(doc.images)}")
    result = extract(doc, template)
    print(result.model_dump_json(indent=2))
