# SenseDoc

**Turn messy documents into clean, validated, structured data — using fields you define.**

SenseDoc is an intelligent document processing (IDP) platform. You describe the data you want (a template of fields and types), upload files in bulk, and SenseDoc extracts those fields from PDFs, scans, phone photos, spreadsheets and Word files. Values it isn't sure about go to a human for review before export, so what comes out can be trusted.

> **Status:** early development. The design is complete; the MVP is being built. Features below marked *(planned)* are not available yet.

---

## Why

Many teams still copy data by hand from invoices, receipts, price lists, shelf photos, CVs and waybills into spreadsheets. It is slow, error-prone and does not scale. SenseDoc automates that work while showing where every value came from and how confident it is.

**Built for:** data analysts, operations and finance teams, and market research firms. For example, a retail data company tracking prices by brand, variant and size (Coca-Cola Original vs Zero, 35cl vs 50cl).

## How it works

```
Define template → Upload files → Extract text → LLM extraction → Validate → Score confidence
                                                                                  │
                                                     ┌────────────────────────────┴───────────┐
                                                high confidence                        low confidence
                                                     │                                        │
                                                  Export  ◄──────────────────────────  Human review
```

1. **Define a template.** Name the fields you want and their types (text, number, date, currency, list, table), with optional descriptions and examples.
2. **Upload files.** PDF, scanned PDF, JPG/PNG, XLSX/CSV and DOCX, in bulk.
3. **Extract text.** Native PDF text, OCR for scans and photos, direct parsing for spreadsheets, and a vision model for leaflets and photos where layout matters.
4. **Extract fields.** Your template becomes a Pydantic model at runtime, and the LLM must return valid JSON matching it. Bad output is re-prompted, then retried on a stronger model.
5. **Validate.** Type checks, required fields, cross-field rules (line items sum to the total) and normalization (50cl → 500 ml, date formats).
6. **Review.** Low-confidence values are shown beside the source document to approve or correct.
7. **Export.** CSV, Excel or JSON.

## Features

| Feature | Status |
| --- | --- |
| Schema builder | MVP |
| Multi-format ingestion (PDF, scans, images, XLSX/CSV, DOCX) | MVP |
| LLM structured extraction with retries and fallbacks | MVP |
| Validation and normalization | MVP |
| Per-field confidence scores | MVP |
| Human review queue | MVP |
| Product and variant matching to a SKU catalogue | MVP |
| CSV / Excel / JSON export | MVP |
| Source highlighting (click a value to see it in the document) | *planned* |
| Automatic document classification | *planned* |
| Model routing (cheap model for easy pages) | *planned* |
| REST API webhooks | *planned* |
| Analytics dashboard | *planned* |

### Product and variant matching

SenseDoc ties every price to one exact product variant, not just a brand. It extracts brand, flavour, size, pack type, pack count and price basis as separate fields, then matches each row against your SKU catalogue. If more than one SKU could fit, the row goes to review with the top candidates. **It never guesses.** Reviewer choices are saved as aliases so the same wording matches automatically next time.

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend API | Python, FastAPI |
| Schemas and validation | Pydantic |
| LLM orchestration | LangChain |
| Background jobs | Celery + Redis |
| PDF / layout / OCR | PyMuPDF, Docling or Surya, PaddleOCR (Tesseract fallback) |
| Spreadsheets / Word | pandas, openpyxl, python-docx |
| Models | One API model (OpenAI, Claude or Gemini) + one open-weight vision model |
| Database | PostgreSQL |
| Frontend | React (Streamlit for the first version) |
| Observability | Langfuse |
| Deployment | Docker Compose |

## API overview *(planned)*

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/templates` | Create a template |
| GET | `/templates`, `/templates/{id}` | List or view templates |
| PUT | `/templates/{id}` | Edit a template (creates a new version) |
| POST | `/documents` | Upload files against a template |
| GET | `/documents/{id}` | Status and extracted values |
| GET | `/review-queue` | Values waiting for review |
| PATCH | `/values/{id}` | Approve or correct a value |
| GET | `/templates/{id}/export?format=csv\|xlsx\|json` | Export approved data |
| GET | `/metrics` | Accuracy, review rate, cost and latency |

## Getting started

Setup instructions will be added once the first runnable version is in place.

## Evaluation

SenseDoc will be measured against a hand-labelled test set of 150–200 documents (invoices, receipts, price lists and shelf photos, CVs or waybills), including deliberately hard cases such as blurry photos, rotated pages and multi-page tables. The evaluation runs in CI on every change.

**Targets** (to be replaced with measured results):

| Metric | Target |
| --- | --- |
| Field-level accuracy | ≥ 90% |
| Variant accuracy (correct SKU) on auto-approved rows | ≥ 95% |
| Fields auto-approved without review | ≥ 70% |
| Median processing time per page | ≤ 10 s |
| Cost per 1,000 pages | Reported per model route |

## Roadmap

- [ ] Core pipeline: upload → extract → validate → export
- [ ] Review queue and confidence scoring
- [ ] Product and variant matching
- [ ] Evaluation set and CI accuracy runs
- [ ] Hosted version with ready-made templates (invoice, receipt, price list)
- [ ] Demo video and evaluation report
