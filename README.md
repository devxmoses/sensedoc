# SenseDoc

**An AI platform for your documents: extract the data you need, and ask questions about the rest.**

Upload PDFs, scans, phone photos, spreadsheets and Word files in bulk. SenseDoc reads them once and gives you two capabilities:

- **Extraction.** Define the fields you want (a template of names and types) and get clean, validated, structured data. Values it isn't sure about go to a human for review before export.
- **Knowledge assistant.** Ask questions in plain language, such as "What are the payment terms on invoice INV-104?", and get answers from your own documents, with the document and page cited. If the answer isn't in your files, SenseDoc says so.

> **Status:** working end to end: templates, multi-format upload, OCR with source highlighting, LLM extraction with retries and fallback, validation and confidence, review queue, product/variant matching, export, knowledge assistant with citations, labelling of real documents for evaluation, metrics, tests and Docker. Items marked *(planned)* are not built yet. A step-by-step explanation of how it was built is in [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

---

## Why

Many teams still copy data by hand from invoices, receipts, price lists, shelf photos, CVs and waybills into spreadsheets, and open files one by one to answer simple questions. Both are slow, error-prone and do not scale. SenseDoc automates both, while showing where every value and every answer came from.

**Built for:** data analysts, operations and finance teams, market research firms, and anyone who needs answers from contracts, policies, reports or invoices. For example, a retail data company tracking prices by brand, variant and size (Coca-Cola Original vs Zero, 35cl vs 50cl), then asking "Which shop had the cheapest Coke Zero 50cl this week?"

## How it works

### Extraction

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

### Knowledge assistant

```
Uploaded files → Parsed text → Chunks + embeddings → Retrieve relevant chunks → LLM answer with citations
```

1. **Reuse the parsed text.** The same text extraction step feeds both capabilities.
2. **Index.** Text is split into chunks by page, embedded (`gemini-embedding-001`), and stored in PostgreSQL with **pgvector** and an HNSW index (Docker and Supabase), or as JSON on local SQLite.
3. **Retrieve.** Your question is matched to the most relevant chunks.
4. **Answer.** The LLM answers only from those chunks and cites the document and page, or says the answer isn't there.
5. **Exact numbers.** Questions about totals across many files are answered from the validated extracted data, not raw text.

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
| Source highlighting (click a value to see it in the document) | MVP |
| Automatic document classification | *planned* |
| Model routing (cheap model for easy pages) | *planned* |
| REST API webhooks | *planned* |
| Analytics dashboard | *planned* |
| Knowledge assistant: ask questions about your documents (RAG) | MVP |
| Label real documents for evaluation | MVP |
| API token, optional sign-in, file retention | MVP |

### Product and variant matching

SenseDoc ties every price to one exact product variant, not just a brand. It extracts brand, flavour, size, pack type, pack count and price basis as separate fields, then matches each row against your SKU catalogue: hard attributes must agree, flavours are compared by spelling first and by meaning (embeddings) when spelling can't decide, so "Coke Light" finds the Diet SKU. If more than one SKU could fit, the row goes to review with the top candidates. **It never guesses.** Reviewer choices are saved as aliases so the same wording matches automatically next time.

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend API | Python, FastAPI |
| Schemas and validation | Pydantic |
| LLM orchestration | LangChain (extraction and the knowledge assistant) |
| Background jobs | Celery + Redis |
| PDF / OCR | PyMuPDF; RapidOCR (PaddleOCR models in ONNX, CPU-only) |
| Spreadsheets / Word | pandas, openpyxl, python-docx |
| Models | One API model (OpenAI, Claude or Gemini) + one open-weight vision model |
| Database | PostgreSQL + pgvector, e.g. Supabase (SQLite for local runs) |
| File storage | Supabase Storage (local disk for local runs) |
| Frontend | React (Streamlit for the first version) |
| Observability | Langfuse |
| Deployment | Docker Compose |

## API overview

Interactive docs at `http://localhost:8000/docs` once the API is running.

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
| POST | `/ask` | Ask a question about uploaded documents; answer with citations |
| GET | `/documents/{id}/preview?value_id=` | Page image with that value boxed (source highlighting) |
| POST | `/documents/{id}/label`, GET `/labels` | Save a verified document as a test label |

## Getting started

You need [uv](https://docs.astral.sh/uv/) and a Gemini API key.

```bash
git clone <this repo> && cd sensedoc
uv sync
cp .env.example .env        # then add your GOOGLE_API_KEY

uv run uvicorn sensedoc.api:app     # landing page + API: http://localhost:8000
uv run streamlit run ui/app.py      # web app:            http://localhost:8501
```

On first start, SenseDoc creates a local SQLite database and loads three ready-made templates (invoice, receipt, product price list) and a sample SKU catalogue. Demo files are in `samples/demo/`.

**Hosted database and file storage with Supabase:** put the project's connection string in `DATABASE_URL` and its URL and service key in `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` (see `.env.example` and [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md), Step 13). On first start SenseDoc enables pgvector, creates the tables and a private storage bucket.

**Full stack with Docker** (PostgreSQL + pgvector, Redis, API, Celery worker, UI):

```bash
docker compose up --build
```

**Tests and evaluation:**

```bash
uv run pytest -q                                   # 36 tests, no API key needed
uv run python evaluation/make_dataset.py           # build the synthetic labelled set
uv run python evaluation/run_eval.py               # measure accuracy, cost and latency
EVAL_ROUTE=ocr uv run python evaluation/run_eval.py   # Experiment 1b: OCR text instead of images
uv run python evaluation/export_labels.py          # real documents labelled in the app → evaluation/real/
EVAL_SET=real uv run python evaluation/run_eval.py # accuracy on real documents
```

**Optional settings** (`.env`): `API_TOKEN` protects the API, `RETENTION_DAYS` deletes old uploads, `EXTRACTION_ROUTE` picks `vision`/`ocr`/`hybrid`. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` to require sign-in to the web app.

### Project layout

| Path | What's there |
| --- | --- |
| `src/sensedoc/schema_builder.py` | Templates → Pydantic models at runtime |
| `src/sensedoc/readers.py`, `ocr.py` | PDF, scans, images, Excel/CSV, Word → text, images and line positions (OCR) |
| `src/sensedoc/extractor.py` | Gemini via LangChain, with re-prompting, fallback and cost tracking |
| `src/sensedoc/validator.py`, `normalize.py` | Grounding, required fields, sum rules, normalization, confidence |
| `src/sensedoc/matching.py` | Product/variant matching to the SKU catalogue |
| `src/sensedoc/pipeline.py`, `worker.py` | The per-document pipeline and background jobs (Celery) |
| `src/sensedoc/db.py`, `api.py`, `export.py` | Database tables, REST API, CSV/Excel/JSON export |
| `src/sensedoc/assistant.py`, `embeddings.py` | Knowledge assistant (chunking, pgvector retrieval, cited answers); shared embeddings |
| `src/sensedoc/storage.py` | Uploaded files on local disk or in Supabase Storage |
| `ui/` | Streamlit web app |
| `web/index.html` | Landing page |
| `templates/` | Ready-made templates |
| `evaluation/` | Synthetic set generator, real-label export, evaluation script, results |
| `tests/` | pytest suite |

## Evaluation

SenseDoc will be measured against a hand-labelled test set of 150–200 documents (invoices, receipts, price lists and shelf photos, CVs or waybills), including deliberately hard cases such as blurry photos, rotated pages and multi-page tables, plus 50+ question/answer pairs over the same documents for the knowledge assistant. The evaluation runs in CI on every change.

**Targets** (to be replaced with measured results):

| Metric | Target |
| --- | --- |
| Field-level accuracy | ≥ 90% |
| Variant accuracy (correct SKU) on auto-approved rows | ≥ 95% |
| Fields auto-approved without review | ≥ 70% |
| Median processing time per page | ≤ 10 s |
| Cost per 1,000 pages | Reported per model route |
| Correct answers to test questions | ≥ 85% |
| Citations that support the answer | ≥ 95% |
| Correct refusal when the answer isn't in the files | ≥ 90% |

## Roadmap

- [x] Core pipeline: upload → extract → validate → export
- [x] Review queue and confidence scoring
- [x] Product and variant matching
- [x] Evaluation set and CI accuracy runs (synthetic set of 17)
- [x] OCR with line positions and source highlighting; Experiment 1b (vision vs OCR text)
- [x] Knowledge assistant: ask questions about uploaded documents (RAG)
- [x] Labelling tool for a real-document evaluation set
- [ ] Collect and label 150–200 real documents; publish `RESULTS_REAL.md`
- [ ] Hosted version with ready-made templates (invoice, receipt, price list)
- [ ] Demo video and write-up
