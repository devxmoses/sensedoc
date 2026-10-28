"""Measure SenseDoc on a labelled test set and save the results.

Synthetic set:  uv run python evaluation/run_eval.py            -> results.json, RESULTS.md
Real set:       EVAL_SET=real uv run python evaluation/run_eval.py  -> results_real.json, RESULTS_REAL.md
(build the real set first with evaluation/export_labels.py)
"""

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz

from sensedoc import config
from sensedoc.extractor import extract
from sensedoc.matching import Product, match_products
from sensedoc.readers import read_document
from sensedoc.schema_builder import Template
from sensedoc.validator import squash, validate

ROOT = Path(__file__).resolve().parent
EVAL_SET = os.getenv("EVAL_SET", "synthetic")  # "synthetic" or "real"
DATASET = ROOT / ("real" if EVAL_SET == "real" else "dataset")
SUFFIX = "_real" if EVAL_SET == "real" else ""
# free-tier keys allow only a few requests per minute, so documents run one at a time
PAUSE_S = float(os.getenv("EVAL_PAUSE_S", "12"))
MODEL = os.getenv("EVAL_MODEL", config.GEMINI_MODEL)  # one model per run, no fallback, so results are comparable
# Experiment 1: what the model gets for photos and scans: "vision" (image), "ocr" (OCR text) or "hybrid" (both)
ROUTE = os.getenv("EVAL_ROUTE", "vision")
CACHE = ROOT / "runs" / EVAL_SET / MODEL / ROUTE  # one result file per document: a quota cut-off never loses finished work
TEMPLATES = {p.stem: Template.model_validate_json(p.read_text()) for p in (config.PROJECT_ROOT / "templates").glob("*.json")}


def load_catalogue() -> list[Product]:
    import csv

    snapshot = DATASET / "catalogue.csv"  # the real set carries the catalogue it was labelled against
    path = snapshot if snapshot.exists() else config.PROJECT_ROOT / "samples" / "catalogue.csv"
    with open(path) as f:
        return [
            Product(r["sku"], r["brand"], r["type"], float(r["size_ml"]), r["pack_type"], int(float(r["pack_count"])),
                    [a for a in r["brand_aliases"].split(";") if a])
            for r in csv.DictReader(f)
        ]


def same(predicted, expected) -> bool:
    """Exact match for codes, normalized match for numbers, dates and names."""
    if expected is None:
        return predicted is None
    if predicted is None:
        return False
    if isinstance(expected, (int, float)):
        try:
            return abs(float(predicted) - expected) < 0.01
        except (TypeError, ValueError):
            return False
    p, e = squash(str(predicted)), squash(str(expected))
    return p == e or fuzz.ratio(p, e) >= 92


def pair_rows(expected: list[dict], predicted: list[dict], text_key: str) -> list[tuple[int, int]]:
    """Greedily pair each expected table row with the most similar predicted row."""
    pairs, used = [], set()
    for ei, e in enumerate(expected):
        best, best_score = None, 0
        for pi, p in enumerate(predicted):
            if pi in used:
                continue
            score = fuzz.token_set_ratio(squash(str(e.get(text_key))), squash(str(p.get(text_key) or "")))
            if "price" in e and same(p.get("price"), e["price"]):
                score += 30  # the price tells "33cl ₦280" and "35cl ₦300" apart
            if score > best_score:
                best, best_score = pi, score
        if best is not None and best_score >= 60:
            used.add(best)
            pairs.append((ei, best))
    return pairs


def row_text_key(row: dict) -> str:
    """The column that names a table row, used to pair expected and predicted rows."""
    for key in ("product_text", "product", "description", "item", "name"):
        if key in row:
            return key
    return next((k for k, v in row.items() if isinstance(v, str)), next(iter(row)))


def evaluate_case(case: dict, catalogue: list[Product]) -> dict:
    template = Template(**case["template_json"]) if "template_json" in case else TEMPLATES[case["template"]]
    doc = read_document(DATASET / case["file"])
    try:
        out = extract(doc, template, models=[MODEL], route=ROUTE)
    except Exception as e:
        return {**case, "error": str(e)[:300]}

    data = out.data.model_dump(mode="json")
    results = validate(out.data, template, doc) + match_products(out.data.model_dump(), template, catalogue)
    status = {r.name: r.status for r in results}
    expected = case["expected"]
    checks = []  # (field path, correct?, status)
    rows_found = rows_expected = rows_predicted = 0
    variant = []  # (expected sku or None, predicted sku, status)

    for key, exp in expected.items():
        if isinstance(exp, list):
            predicted = data.get(key) or []
            text_key = row_text_key(exp[0]) if exp else "product"
            pairs = pair_rows(exp, predicted, text_key)
            rows_found += len(pairs)
            rows_expected += len(exp)
            rows_predicted += len(predicted)
            for ei, pi in pairs:
                for column, value in exp[ei].items():
                    if column in ("sku", "product_text"):
                        continue
                    path = f"{key}[{pi}].{column}"
                    checks.append((path, same(predicted[pi].get(column), value), status.get(path)))
                if "sku" in exp[ei]:
                    path = f"{key}[{pi}].sku"
                    sku_result = next(r for r in results if r.name == path)
                    variant.append((exp[ei]["sku"], sku_result.value, sku_result.status))
        else:
            checks.append((key, same(data.get(key), exp), status.get(key)))

    return {
        **case,
        "model": out.model,
        "latency_ms": out.latency_ms,
        "cost_usd": out.cost_usd,
        "pages": doc.page_count,
        "checks": checks,
        "review_rate": sum(r.status == "needs_review" for r in results) / max(len(results), 1),
        "rows": (rows_found, rows_expected, rows_predicted),
        "variant": variant,
    }


def summarize(cases: list[dict]) -> dict:
    ok = [c for c in cases if "error" not in c]
    checks = [ch for c in ok for ch in c["checks"]]
    auto = [correct for _, correct, s in checks if s == "auto_approved"]
    review = [correct for _, correct, s in checks if s == "needs_review"]
    found, expected, predicted = (sum(c["rows"][i] for c in ok) for i in range(3))
    variants = [v for c in ok for v in c["variant"]]
    auto_variants = [v for v in variants if v[2] == "auto_approved"]
    must_review = [v for v in variants if v[0] is None]
    return {
        "documents": len(cases),
        "failed": len(cases) - len(ok),
        "fields_checked": len(checks),
        "field_accuracy": sum(c for _, c, _ in checks) / max(len(checks), 1),
        "auto_approved_accuracy": sum(auto) / max(len(auto), 1),
        "needs_review_accuracy": sum(review) / max(len(review), 1),
        "review_rate": statistics.mean(c["review_rate"] for c in ok) if ok else 0,
        "row_recall": found / max(expected, 1),
        "row_precision": found / max(predicted, 1),
        "variant_rows": len(variants),
        "variant_accuracy": sum(v[0] == v[1] for v in auto_variants) / max(len(auto_variants), 1),
        "variant_auto_approved": len(auto_variants),
        "unclear_rows_sent_to_review": f"{sum(v[2] == 'needs_review' for v in must_review)}/{len(must_review)}",
        "median_latency_s": statistics.median(c["latency_ms"] for c in ok) / 1000 if ok else None,
        "cost_per_1000_pages_usd": sum(c["cost_usd"] for c in ok) / max(sum(c["pages"] for c in ok), 1) * 1000,
    }


def table_row(label: str, s: dict) -> dict:
    if s["failed"] == s["documents"]:
        return {"group": label, "documents": s["documents"], "field accuracy": "not run (all failed)"}
    return {
        "group": label,
        "documents": s["documents"] - s["failed"],
        "field accuracy": f"{s['field_accuracy']:.0%}",
        "auto-approved accuracy": f"{s['auto_approved_accuracy']:.0%}",
        "review rate": f"{s['review_rate']:.0%}",
        "median seconds": f"{s['median_latency_s']:.1f}" if s["median_latency_s"] else "–",
        "USD per 1,000 pages": f"{s['cost_per_1000_pages_usd']:.2f}",
    }


def main() -> None:
    cases = json.loads((DATASET / "labels.json").read_text())
    if ROUTE != "vision":  # the route only changes what is sent for photos and scans
        cases = [c for c in cases if c.get("route") == "vision"]
    catalogue = load_catalogue()
    started = time.perf_counter()
    CACHE.mkdir(parents=True, exist_ok=True)
    done = []
    for case in cases:
        cached = CACHE / f"{case['file']}.json"
        if cached.exists():
            c = json.loads(cached.read_text())
        else:
            if done:
                time.sleep(PAUSE_S)
            c = evaluate_case(case, catalogue)
            if "error" not in c:
                cached.write_text(json.dumps(c))
        done.append(c)
        if "error" in c:
            print(f"FAILED {c['file']}: {c['error'][:150]}", flush=True)
        else:
            wrong = [p for p, ok, _ in c["checks"] if not ok]
            print(f"{c['file']:<24} {c['latency_ms'] / 1000:5.1f}s  wrong: {wrong or '-'}", flush=True)

    summary = summarize(done)
    # synthetic set: the same invoices on both routes; real set: every document on its own route
    same_docs = (lambda c: c["template"] == "invoice") if EVAL_SET == "synthetic" else (lambda c: True)
    routes = [table_row(f"{r} route", summarize(group))
              for r in ("text", "vision") if (group := [c for c in done if c.get("route") == r and same_docs(c)])]
    templates = sorted({c["template"] for c in done})
    by_type = [table_row(t, summarize([c for c in done if c["template"] == t])) for t in templates]

    images_only = summarize([c for c in done if c.get("route") == "vision"])
    results = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "set": EVAL_SET,
        "photo_route": ROUTE,
        "photo_summary": images_only,  # photos and scans only: compared across routes in Experiment 1
        "documents": len(done),
        "wall_clock_s": round(time.perf_counter() - started, 1),
        "summary": summary,
        "routes": routes,
        "by_type": by_type,
    }
    if ROUTE != "vision":  # a side experiment: keep it apart from the main results
        (ROOT / f"results{SUFFIX}_{ROUTE}.json").write_text(json.dumps(results, indent=2))
        main_results = ROOT / f"results{SUFFIX}.json"
        if main_results.exists():
            write_markdown(json.loads(main_results.read_text()))
    else:
        (ROOT / f"results{SUFFIX}.json").write_text(json.dumps(results, indent=2))
        write_markdown(results)
    print(json.dumps(summary, indent=2))


def write_markdown(r: dict) -> None:
    s = r["summary"]

    def md_table(rows: list[dict]) -> str:
        head = "| " + " | ".join(rows[0]) + " |\n| " + " | ".join("---" for _ in rows[0]) + " |\n"
        return head + "\n".join("| " + " | ".join(str(v) for v in row.values()) + " |" for row in rows)

    if r["set"] == "real":
        title, about = "on real documents", "Real files you uploaded and verified in the Label for testing page."
        route_note = "Each document on the route it needed: text when the file contains text, vision for photos and scans."
        caveat = "- These are real, hand-verified documents. This is the number to quote."
    else:
        title = "on the synthetic set"
        about = ("Invoices as digital PDF and as tilted, blurred photos; receipt photos; "
                 "supermarket leaflets with look-alike variants.")
        route_note = "The same six invoices, once as a digital PDF (text sent to the model) and once as a phone-style photo (image sent)."
        caveat = ("- The documents are **synthetic**: generated with known answers, then tilted and blurred to imitate photos.\n"
                  "  A perfect score means this set is too easy, not that SenseDoc is perfect. Quote results on real documents instead.")

    photo_routes = [table_row("vision (image)", r["photo_summary"])]
    for route in ("ocr", "hybrid"):
        other = ROOT / f"results{'_real' if r['set'] == 'real' else ''}_{route}.json"
        if other.exists() and json.loads(other.read_text())["model"] == r["model"]:
            photo_routes.append(table_row(f"{route} (OCR text{' + image' if route == 'hybrid' else ''})",
                                          json.loads(other.read_text())["photo_summary"]))

    text = f"""# SenseDoc evaluation results {title}

Run {r['run_at'][:16]} UTC · model `{r['model']}` · {r['documents']} labelled documents ({s['failed']} failed to process)
{about}

| Metric | Result | Target |
| --- | --- | --- |
| Field-level accuracy | {s['field_accuracy']:.1%} ({s['fields_checked']} fields) | ≥ 90% |
| Accuracy of auto-approved values | {s['auto_approved_accuracy']:.1%} | high, i.e. confidence is trustworthy |
| Fields sent to review | {s['review_rate']:.1%} | ≤ 30% |
| Table rows found (recall / precision) | {s['row_recall']:.1%} / {s['row_precision']:.1%} | – |
| Variant accuracy on auto-approved product rows | {s['variant_accuracy']:.1%} ({s['variant_auto_approved']} rows) | ≥ 95% |
| Unclear product rows sent to review (never guessed) | {s['unclear_rows_sent_to_review']} | all |
| Median processing time per document | {s['median_latency_s']:.1f} s | ≤ 10 s |
| Cost per 1,000 pages | ${s['cost_per_1000_pages_usd']:.2f} | reported |

## Experiment 1: text route vs vision route
{route_note}

{md_table(r['routes'])}

## Experiment 1b: what to send the model for photos and scans
The same {r['photo_summary']['documents']} photo/scan documents, same model. *vision* sends the image; *ocr* sends only the text
that RapidOCR read (runs on the CPU, no image tokens); *hybrid* sends both. Compare field accuracy, time and cost;
review rates can differ because confirming values with OCR was added between runs.

{md_table(photo_routes)}

## By document type

{md_table(r['by_type'])}

## How to read these numbers

{caveat}
- "Never guessed" is the key safety result: every product line the leaflet left ambiguous went to review instead of getting a SKU.
- Costs use ${config.PRICE_INPUT_PER_M} / ${config.PRICE_OUTPUT_PER_M} per million input/output tokens (set in `.env`). If the model above
  is cheaper than that (e.g. a "lite" model), the real cost is lower.
- A free-tier Gemini key allows about 20 requests per model per day; results are cached in `evaluation/runs/` so a run can resume.
Reproduce with `uv run python evaluation/make_dataset.py && uv run python evaluation/run_eval.py`.
"""
    (ROOT / f"RESULTS{SUFFIX}.md").write_text(text)


if __name__ == "__main__":
    main()
