# SenseDoc: how it was built, step by step

This guide explains every part of SenseDoc in the order it was built, what each piece does, and why. It ends with a demo script and likely questions for a presentation.

---

## The idea in one sentence

**SenseDoc turns messy documents (invoices, receipts, price lists, phone photos) into validated, structured data using fields the user defines, and only asks a person about the values it is unsure of.**

```
Define template → Upload files → Read (text or image) → LLM extraction → Validate → Confidence
                                                                                     │
                                                         ┌───────────────────────────┴──────────┐
                                                   high confidence                       low confidence
                                                         │                                      │
                                                      Export  ◄─────────────────────────  Human review
```

```mermaid
flowchart LR
    UI[Streamlit app] -->|HTTP| API[FastAPI]
    Landing[Landing page] --- API
    API -->|saves file, queues job| Q[(Redis queue)]
    Q --> W[Celery worker]
    W --> P[Pipeline: read → extract → validate → match]
    P -->|Gemini| LLM((LLM))
    P --> DB[(PostgreSQL)]
    API --> DB
```

| Layer | Tool | Job |
| --- | --- | --- |
| Schemas | Pydantic | Turn a user's template into a strict data model |
| LLM | Gemini via LangChain | Read the document and fill the model |
| Reading files | PyMuPDF, pandas, python-docx | PDF text and page images, Excel/CSV, Word |
| Checks | Our own validator | Grounding, required fields, sum rules, confidence |
| Matching | rapidfuzz | Tie each price to one exact product SKU |
| API | FastAPI | Upload, status, review, export, metrics |
| Jobs | Celery + Redis | Slow LLM work runs outside web requests |
| Database | PostgreSQL (SQLite locally) | Templates, documents, runs, values, reviews, products |
| UI | Streamlit + an HTML landing page | Everything a user clicks |
| Quality | pytest + an evaluation script | Tests on every change; measured accuracy |
| Deploy | Docker Compose | One command starts the whole stack |

---

## Step 0: Project setup

- **uv** manages Python and packages. Each project has its own *virtual environment* (`.venv/`), so libraries never clash between projects.
- **Python 3.12**, not the newest 3.14, because AI and OCR libraries take time to support new Python versions.
- **Pydantic** is the foundation. You describe the *shape* data must have (`total_amount: float`), and Pydantic either converts the input to that shape or raises a clear error. LLM output can't be trusted, so everything the model returns passes through Pydantic.

## Step 1: First extraction (PDF → LLM → structured data)

- **PyMuPDF** reads the text out of a digital PDF.
- The API key lives in **`.env`**, never in code, and `.env` is in `.gitignore`.
- **`with_structured_output(Invoice)`** (LangChain) sends the Pydantic model's JSON schema to Gemini. The model must answer with exactly those fields and types, and we get a Python object back, not text to pick apart.
- Every field allows `None`, so the model can say "not shown" instead of inventing a value. Required fields are enforced later, by our own checks.

## Step 2: Templates become schemas at runtime

Users define their own fields, so we can't hand-write a class for every template.

- A template is plain data (JSON or a database row): field names, types (`text`, `number`, `date`, `currency`, `list`, `table`), required flags, descriptions and examples.
- `build_model()` (in `schema_builder.py`) uses Pydantic's **`create_model`** to build the class while the program runs. A `table` field calls `build_model` on its own columns (**recursion**), giving `list[Row]`.
- `to_key()` turns friendly names into Python names: `"Invoice Number"` → `invoice_number`.
- Descriptions and examples are put into the schema the model reads, so better descriptions mean better accuracy.

## Step 3: Any file type

`readers.py` returns a `ParsedDocument` holding **text and/or images**:

| File | How it's read |
| --- | --- |
| Digital PDF | Text per page (cheap and exact) |
| Scanned PDF page (less than 50 characters of text) | The page is rendered to a 200-DPI image |
| JPG / PNG / WEBP | Sent as an image |
| XLSX / CSV | Every sheet converted to CSV text (pandas) |
| DOCX | Paragraphs and tables as text (python-docx) |

**Rule: text if available, image if not.** Images cost more tokens, and text is exact. For images, Gemini is a **vision model**: it sees the layout, so it knows which price sits next to which product picture. The message to the model is **multimodal**: a list of text parts and base64-encoded images.

> Plan decision: OCR (PaddleOCR) is deferred to Step 8b. It will add word positions (for click-to-see-source) and per-word confidence, and the evaluation will compare it against vision (Experiment 1).

## Step 4: Validation, normalization and confidence

**Never trust the model blindly.** An LLM gives a confident-looking answer even when a photo is blurry. `validator.py` checks every value:

| Check | Question | Effect |
| --- | --- | --- |
| Grounding | Is this value actually printed in the document text? | Not found: −0.4 (likely hallucinated) |
| Image only | Was it read from a picture, with no text to cross-check? | Confidence set to 0.85 |
| Required | Is a required field missing? | Confidence 0 |
| Sum rules | Do line totals add up to the subtotal? Subtotal + tax = total? | Every value involved −0.3 |
| Normalization | Can `50cl` / `1.5L` be converted to ml? | Failure −0.3 |

A value **at or above 0.8 is auto-approved**. Below that, it goes to a person. Each value is checked on its own, so in a table each cell can be reviewed separately (`items[2].unit_price`).

Grounding compares the value in all the ways it might be printed (`12000.0` vs `12,000.00`, `2026-10-14` vs `14 October 2026`).

Why layered checks matter: if `4,200` is misread as `4,800`, grounding *passes*, because 4,800 appears elsewhere on the page. The **sum rule** catches it. No single check catches everything.

> The confidence numbers are rules, not probabilities. The evaluation measures **calibration** ("of auto-approved values, how many were right?") so the thresholds can be tuned with evidence.

Rules live **inside the template** (`"rules": [...]`), because every business has different rules.

## Step 5: Retries, fallbacks and cost tracking (`extractor.py`)

The plan's error-recovery chain, in code:

1. Ask the main model (`gemini-3.6-flash`).
2. If the answer is broken (bad JSON, wrong types), **re-prompt with the exact error**, up to 2 times.
3. If the model is down or overloaded, move to the **fallback model** (`gemini-3.5-flash`).
4. If the API says "too many requests" (rate limit), **wait and retry** instead of failing.
5. If everything fails, the document is marked `failed` with the reason. The job never crashes.

Every run records the model used, tokens in and out, **cost in USD**, latency and attempts.

## Step 6: Database and REST API

**Database (`db.py`)**: the plan's tables, defined with SQLAlchemy:

| Table | One row is... |
| --- | --- |
| `templates` / `template_fields` | a template version and its fields (table columns point to their parent field) |
| `documents` | an uploaded file, with status `queued → processing → needs_review / done / failed` |
| `extraction_runs` | one attempt: model, tokens, cost, latency |
| `extracted_values` | **one value** with its confidence, status, issues and matched SKU |
| `reviews` | an audit trail of every human approval or correction |
| `products` | the SKU catalogue, including aliases learned from corrections |

Editing a template **creates a new version**, so old results always match the template that produced them.

SQLite is used locally (no setup); Docker Compose switches to PostgreSQL by changing one setting, `DATABASE_URL`.

**API (`api.py`)**: FastAPI, with automatic interactive docs at `/docs`:

| Endpoint | Purpose |
| --- | --- |
| `POST /templates`, `GET /templates`, `PUT /templates/{id}` | Create, list, edit (new version) |
| `POST /documents` | Upload many files; returns at once and queues the work |
| `GET /documents/{id}` | Status, values, confidence, cost |
| `GET /documents/{id}/preview` | A PNG of the page, for the review screen |
| `GET /review-queue` | Values waiting for a person, oldest first |
| `PATCH /values/{id}` | Approve or correct (written to `reviews`) |
| `GET /templates/{id}/export?format=csv\|xlsx\|json` | Approved data |
| `GET /products`, `POST /products/import` | The SKU catalogue |
| `GET /metrics` | Auto-approval rate, latency, cost, evaluation results |

## Step 7: Background jobs (`worker.py`)

An LLM call takes 5–20 seconds. A web request must never wait that long. So the API only **saves the file and queues a job**, then answers immediately.

- With Docker, jobs go through **Redis** (the queue) to a **Celery worker** (the process that does the work). Workers can be scaled up for bulk uploads.
- Locally, without Redis, the same `process_document()` function runs in a FastAPI background task, so the demo needs no extra services.

`pipeline.py` holds that one function: **read → extract → validate → match products → save the run and every value → set the document status.**

## Step 8: Product and variant matching (`matching.py`)

On a leaflet that says "Coke", the price might belong to any of 9+ SKUs. The plan's rule: **never guess**.

1. **Saved alias?** If a reviewer already said what this exact wording means, use it.
2. **Filter by hard attributes**: brand (with aliases such as "Coke" → Coca-Cola), size in ml, pack type (can / PET / glass), pack count. Any that disagree are out.
3. **Rank by flavour** (Original, Zero Sugar, Diet...) using fuzzy text similarity.
4. **Decide:** exactly one SKU fits → matched. More than one → `needs_review` with the **top 3 candidates** and the reason ("size missing; 2 SKUs fit"). None → review.
5. **Unit price** for packs: ₦5,400 for 12 cans → ₦450 each.
6. **Learn:** when a reviewer picks a SKU, the wording is saved as an alias, so the same leaflet text matches automatically next time.

It reproduces the plan's worked example exactly: Coke 50cl auto-matched; Coke Zero can (no size) → review; Coke 35cl x12 → matched, ₦450/unit; bare "Coke" → review with candidates.

> Deviation: the plan suggests embeddings plus fuzzy matching. Fuzzy matching (rapidfuzz) alone works well here, because the hard-attribute filter does most of the work. Embeddings can be added if catalogues have many free-text names.

## Step 9: The user interface

**Landing page** (`web/index.html`, served at `/`): the problem, how it works, the variant-matching example, and **live evaluation numbers** loaded from `/metrics`.

**Web app** (Streamlit, `ui/`): multi-page, talking to the API over HTTP.

| Page | What it does |
| --- | --- |
| Overview | Key numbers and the six-step flow |
| Upload | Pick a template, drop many files, watch progress live (auto-refreshes every 3 seconds) |
| Documents | Every file with status, cost and time; the page preview beside its values and confidence bars |
| Review queue | Only uncertain values, shown **beside the page**; approve, correct, or pick the right SKU |
| Export | Preview, then download CSV / Excel / JSON |
| Templates | The **schema builder**: an editable table of fields, table columns, rules; saving creates a new version |
| Product catalogue | SKUs, learned aliases, CSV import |
| Metrics | Live usage plus evaluation results, including Experiment 1 |

Streamlit reruns the page script on every click, so anything that must survive (like the list of just-uploaded files) is kept in `st.session_state`.

## Step 10: Testing and evaluation

**Tests (`tests/`, 23 tests, no API key needed):** run with `uv run pytest`. They cover template → schema, normalization, every validation case (correct, misread number, invented value, missing field, image), the plan's variant-matching examples, and the full API loop (upload → review → export) with the LLM replaced by a fake answer. They run in GitHub Actions on every push.

**Evaluation (`evaluation/`):**

- `make_dataset.py` generates **17 labelled documents** whose correct answers we know. Hard cases are included on purpose: invoices as clean PDFs **and** as tilted, blurred phone photos; receipt photos; two supermarket leaflets with look-alike traps (Zero vs Original, can vs bottle, 33cl vs 35cl, a missing size, a "33cl / 35cl – ₦280 / ₦300" line that must be split into two rows, single vs 12-pack).
- `run_eval.py` runs the real pipeline and scores field accuracy, accuracy of auto-approved values (calibration), review rate, row recall and precision, **variant accuracy**, latency and cost per 1,000 pages. It also runs **Experiment 1**: the same invoices via the text route vs the vision route.
- Results are written to `evaluation/RESULTS.md` and shown in the app and on the landing page.

## Step 11: Deployment

`docker compose up --build` starts **PostgreSQL, Redis, the API, a Celery worker and the UI**. One image serves all three app roles. Only the start command differs.

---

## Running it

```bash
uv sync                                   # install everything
uv run uvicorn sensedoc.api:app           # terminal 1: API + landing page → http://localhost:8000
uv run streamlit run ui/app.py            # terminal 2: web app → http://localhost:8501
uv run pytest -q                          # tests
uv run python evaluation/run_eval.py      # accuracy run (uses the Gemini key)
```

On first start, the API creates the database and loads three ready-made templates (Supplier Invoice, Shop Receipt, Product Price List) and a sample product catalogue.

## Demo script (about 5 minutes)

1. **Landing page** (`localhost:8000`): the problem, how it works, the Coke variant table, the measured results.
2. **Templates → View "Product Price List"**: point out that fields are just data, the `Size` field normalizes to ml, and rows are matched to the catalogue.
3. **Upload**: choose *Supplier Invoice* and drop `samples/demo/invoice_00.pdf` and `invoice_01_photo.png` (a tilted, blurred photo). Then *Product Price List* with `samples/demo/leaflet_01.png`. Watch the statuses change live.
4. **Documents**: open the photo invoice. All values are found, at 0.85 confidence because they came from an image. Show cost (under one US cent) and time.
5. **Review queue**: the leaflet's "Coke Zero Can" has no size printed. SenseDoc did not guess: it offers 33cl and 35cl. Pick one and explain it is now **learned** (show it under *Product catalogue → learned aliases*).
6. **Export**: download Excel. One row per product line, with SKU and unit price.
7. **Metrics**: accuracy from the evaluation, plus Experiment 1, text vs vision.

## Likely questions

- **"What if the model makes something up?"** Every value is checked against the page (grounding) and against sum rules. Invented values score low and go to review. Values with no text to check (photos) never get full confidence.
- **"How do you know it's accurate?"** A labelled test set with deliberately hard cases, re-run on every change. We report the accuracy of the values we auto-approve, not just overall accuracy.
- **"What does it cost?"** Tokens are counted per run. Costs are configured in `.env` (the default assumes $1.50 / $7.50 per million input/output tokens; check Google's pricing page). That's well under one US cent per page.
- **"Why not just OCR?"** OCR gives text but loses layout: on a leaflet you need to know which price sits under which product. OCR is still planned (Step 8b), for word positions and as a cheaper route on clean scans, and Experiment 1 will decide when to use which.
- **"What about privacy?"** Keys stay in `.env`; files are stored locally or in a private volume. Still to do: encryption at rest, automatic deletion after a retention period, and authentication.

## What's not built yet

| Item | Status |
| --- | --- |
| OCR route (PaddleOCR) with word boxes → click-to-see-source highlighting | Next (Step 8b) |
| Knowledge assistant (ask questions, answers with citations, RAG) | Marked *planned* in the README |
| Document classification, model routing, webhooks | Later phase in the plan |
| Langfuse tracing | Not added; cost and latency are tracked in our own tables |
| Database migrations (Alembic), authentication, file encryption and retention | Needed before a public hosted version |
| A larger evaluation set (150–200 real documents) | The current 17 are synthetic; real photos are the next step |
