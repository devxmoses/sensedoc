"""Measure SenseDoc on the labelled test set and save the results.

Run:  uv run python evaluation/run_eval.py
It calls the real model (about 17 requests) and writes evaluation/results.json and RESULTS.md.
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
DATASET = ROOT / "dataset"
# free-tier keys allow only a few requests per minute, so documents run one at a time
PAUSE_S = float(os.getenv("EVAL_PAUSE_S", "12"))
MODEL = os.getenv("EVAL_MODEL", config.GEMINI_MODEL)  # one model per run, no fallback, so results are comparable
CACHE = ROOT / "runs" / MODEL  # one result file per document: a quota cut-off never loses finished work
TEMPLATES = {p.stem: Template.model_validate_json(p.read_text()) for p in (config.PROJECT_ROOT / "templates").glob("*.json")}


def load_catalogue() -> list[Product]:
    import csv

    with open(config.PROJECT_ROOT / "samples" / "catalogue.csv") as f:
        return [
            Product(r["sku"], r["brand"], r["type"], float(r["size_ml"]), r["pack_type"], int(r["pack_count"]),
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


def evaluate_case(case: dict, catalogue: list[Product]) -> dict:
    template = TEMPLATES[case["template"]]
    doc = read_document(DATASET / case["file"])
    try:
        out = extract(doc, template, models=[MODEL])
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
            text_key = "product_text" if case["template"] == "price_list" else "product"
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
    routes = [table_row(f"{r} route (invoices)", summarize([c for c in done if c.get("route") == r and c["template"] == "invoice"]))
              for r in ("text", "vision")]
    by_type = [table_row(t, summarize([c for c in done if c["template"] == t])) for t in ("invoice", "receipt", "price_list")]

    results = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "documents": len(done),
        "wall_clock_s": round(time.perf_counter() - started, 1),
        "summary": summary,
        "routes": routes,
        "by_type": by_type,
    }
    (ROOT / "results.json").write_text(json.dumps(results, indent=2))
    write_markdown(results)
    print(json.dumps(summary, indent=2))


def write_markdown(r: dict) -> None:
    s = r["summary"]

    def md_table(rows: list[dict]) -> str:
        head = "| " + " | ".join(rows[0]) + " |\n| " + " | ".join("---" for _ in rows[0]) + " |\n"
        return head + "\n".join("| " + " | ".join(str(v) for v in row.values()) + " |" for row in rows)

    text = f"""# SenseDoc evaluation results

Run {r['run_at'][:16]} UTC · model `{r['model']}` · {r['documents']} labelled documents ({s['failed']} failed to process)
(invoices as digital PDF and as tilted, blurred photos; receipt photos; supermarket leaflets with look-alike variants).

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
The same six invoices, once as a digital PDF (text sent to the model) and once as a phone-style photo (image sent).

{md_table(r['routes'])}

## By document type

{md_table(r['by_type'])}

## How to read these numbers

- The documents are **synthetic**: generated with known answers, then tilted and blurred to imitate photos. A perfect score means
  this set is too easy, not that SenseDoc is perfect. The next step is a set of real phone photos and real supplier invoices.
- "Never guessed" is the key safety result: every product line the leaflet left ambiguous went to review instead of getting a SKU.
- Costs use ${config.PRICE_INPUT_PER_M} / ${config.PRICE_OUTPUT_PER_M} per million input/output tokens (set in `.env`). If the model above
  is cheaper than that (e.g. a "lite" model), the real cost is lower.
- A free-tier Gemini key allows about 20 requests per model per day; results are cached in `evaluation/runs/` so a run can resume.
Reproduce with `uv run python evaluation/make_dataset.py && uv run python evaluation/run_eval.py`.
"""
    (ROOT / "RESULTS.md").write_text(text)


if __name__ == "__main__":
    main()
