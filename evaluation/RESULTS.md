# SenseDoc evaluation results

Run 2026-10-27T11:12 UTC · model `gemini-3.5-flash-lite` · 17 labelled documents (0 failed to process)
(invoices as digital PDF and as tilted, blurred photos; receipt photos; supermarket leaflets with look-alike variants).

| Metric | Result | Target |
| --- | --- | --- |
| Field-level accuracy | 100.0% (274 fields) | ≥ 90% |
| Accuracy of auto-approved values | 100.0% | high, i.e. confidence is trustworthy |
| Fields sent to review | 0.3% | ≤ 30% |
| Table rows found (recall / precision) | 100.0% / 100.0% | – |
| Variant accuracy on auto-approved product rows | 100.0% (10 rows) | ≥ 95% |
| Unclear product rows sent to review (never guessed) | 2/2 | all |
| Median processing time per document | 8.4 s | ≤ 10 s |
| Cost per 1,000 pages | $3.68 | reported |

## Experiment 1: text route vs vision route
The same six invoices, once as a digital PDF (text sent to the model) and once as a phone-style photo (image sent).

| group | documents | field accuracy | auto-approved accuracy | review rate | median seconds | USD per 1,000 pages |
| --- | --- | --- | --- | --- | --- | --- |
| text route (invoices) | 6 | 100% | 100% | 0% | 8.4 | 2.55 |
| vision route (invoices) | 6 | 100% | 100% | 0% | 7.8 | 3.87 |

## By document type

| group | documents | field accuracy | auto-approved accuracy | review rate | median seconds | USD per 1,000 pages |
| --- | --- | --- | --- | --- | --- | --- |
| invoice | 12 | 100% | 100% | 0% | 7.8 | 3.21 |
| receipt | 3 | 100% | 100% | 0% | 13.6 | 3.65 |
| price_list | 2 | 100% | 100% | 2% | 9.9 | 6.52 |

## How to read these numbers

- The documents are **synthetic**: generated with known answers, then tilted and blurred to imitate photos. A perfect score means
  this set is too easy, not that SenseDoc is perfect. The next step is a set of real phone photos and real supplier invoices.
- "Never guessed" is the key safety result: every product line the leaflet left ambiguous went to review instead of getting a SKU.
- Costs use $1.5 / $7.5 per million input/output tokens (set in `.env`). If the model above
  is cheaper than that (e.g. a "lite" model), the real cost is lower.
- A free-tier Gemini key allows about 20 requests per model per day; results are cached in `evaluation/runs/` so a run can resume.
Reproduce with `uv run python evaluation/make_dataset.py && uv run python evaluation/run_eval.py`.
