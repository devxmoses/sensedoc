"""Copy every labelled document and its verified answer into evaluation/real/.

Run:  uv run python evaluation/export_labels.py
Then: EVAL_SET=real uv run python evaluation/run_eval.py

evaluation/real/ is git-ignored: real invoices and receipts can contain personal data.
"""

import csv
import json
from pathlib import Path

from sqlalchemy import select

from sensedoc import storage
from sensedoc.db import LabelRow, ProductRow, SessionLocal, create_tables, template_from_row
from sensedoc.readers import read_document

OUT = Path(__file__).resolve().parent / "real"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    create_tables()
    cases = []
    with SessionLocal() as db:
        for label in db.scalars(select(LabelRow).order_by(LabelRow.id)).all():
            doc = label.document
            name = f"{doc.id:04d}_{Path(doc.filename).name}"
            storage.copy_to(doc.storage_path, OUT / name)
            route = "vision" if read_document(OUT / name).images else "text"
            cases.append(
                {
                    "file": name,
                    "template": doc.template.name,
                    "template_json": template_from_row(doc.template).model_dump(),
                    "route": route,
                    "expected": label.expected,
                }
            )

        # a snapshot of the catalogue, so product matching is scored against the same SKUs
        with open(OUT / "catalogue.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["sku", "brand", "type", "size_ml", "pack_type", "pack_count", "brand_aliases"])
            for p in db.scalars(select(ProductRow)).all():
                writer.writerow([p.sku, p.brand, p.type, p.size_ml, p.pack_type, p.pack_count, ";".join(p.brand_aliases or [])])

    (OUT / "labels.json").write_text(json.dumps(cases, indent=2))
    print(f"Exported {len(cases)} labelled documents to {OUT}")


if __name__ == "__main__":
    main()
