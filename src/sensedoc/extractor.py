"""Send a parsed document plus a template to the LLM and get validated data back."""

import base64
import time
import warnings
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from sensedoc import config
from sensedoc.readers import ParsedDocument
from sensedoc.schema_builder import Template, build_model

# newer Gemini models ignore temperature; the library warns about it on every call
warnings.filterwarnings("ignore", message=".*fixed sampling defaults.*")

PROMPT_VERSION = "v2"
FIX_RETRIES = 2  # re-prompts with the error message before trying the next model
RATE_LIMIT_RETRIES = 4  # waits when the API says "too many requests" (e.g. free-tier quota)
RATE_LIMIT_WAIT_S = 20  # first wait; it grows with each retry

SYSTEM_PROMPT = (
    "You extract data from business documents into the fields requested. "
    "The document may be given as text, as page images, or both. "
    "Only use information that appears in the document. "
    "If a field is not shown, return null. Never guess or fill gaps "
    "from general knowledge. Copy IDs and codes exactly as written."
)


@dataclass
class ExtractionOutput:
    data: BaseModel
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    attempts: int

    @property
    def cost_usd(self) -> float:
        return (self.tokens_in * config.PRICE_INPUT_PER_M + self.tokens_out * config.PRICE_OUTPUT_PER_M) / 1_000_000


class ExtractionFailed(Exception):
    pass


def is_rate_limited(error: Exception) -> bool:
    text = str(error)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower()


def get_llm(model: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=0,
        timeout=60,  # give up after 60 seconds instead of waiting forever
        max_retries=2,  # retry twice on temporary errors like 503
    )


def build_messages(doc: ParsedDocument, template: Template, route: str | None = None) -> list:
    """route: 'vision' sends page images, 'ocr' sends OCR text instead, 'hybrid' sends both."""
    route = route or config.EXTRACTION_ROUTE
    if route != "vision" and not doc.ocr_text:
        route = "vision"  # nothing was OCR'd, so the image is all we have
    content = [{"type": "text", "text": f"Document type: {template.document_type}"}]

    if doc.text:
        content.append({"type": "text", "text": f"Document text:\n\n{doc.text}"})

    if route in ("ocr", "hybrid") and doc.images:
        content.append(
            {"type": "text", "text": f"Text read by OCR from the page images (may contain reading errors):\n\n{doc.ocr_text}"}
        )
    if route == "ocr":
        return [SystemMessage(SYSTEM_PROMPT), HumanMessage(content=content)]

    for image in doc.images:
        content.append(
            {
                "type": "image",
                "base64": base64.b64encode(image.data).decode(),
                "mime_type": image.mime_type,
            }
        )

    return [SystemMessage(SYSTEM_PROMPT), HumanMessage(content=content)]


def extract(
    doc: ParsedDocument, template: Template, models: list[str] | None = None, route: str | None = None
) -> ExtractionOutput:
    """Try each model in turn; on bad output, re-prompt with the error before moving on."""
    schema = build_model("Extraction", template.fields)
    models = models or [config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODEL]
    tokens_in = tokens_out = attempts = 0
    errors = []
    start = time.perf_counter()
    waited = 0.0  # time spent waiting for rate limits is not processing time

    for model in models:
        llm = get_llm(model).with_structured_output(schema, include_raw=True)
        messages = build_messages(doc, template, route)
        fixes = rate_waits = 0

        while fixes <= FIX_RETRIES:
            attempts += 1
            try:
                out = llm.invoke(messages)
            except Exception as e:  # network error, overloaded model, timeout, rate limit...
                if is_rate_limited(e) and rate_waits < RATE_LIMIT_RETRIES:
                    rate_waits += 1
                    pause = RATE_LIMIT_WAIT_S * rate_waits
                    time.sleep(pause)
                    waited += pause
                    continue  # same model, same question, after a pause
                errors.append(f"{model}: {type(e).__name__}: {str(e)[:300]}")
                break  # this model is unavailable: go to the next one

            usage = getattr(out["raw"], "usage_metadata", None) or {}
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)

            if out["parsed"] is not None:
                return ExtractionOutput(
                    data=out["parsed"],
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=int((time.perf_counter() - start - waited) * 1000),
                    attempts=attempts,
                )

            # bad JSON or wrong types: tell the model what went wrong and ask again
            fixes += 1
            error = out.get("parsing_error") or "no structured answer returned"
            errors.append(f"{model}: {error}")
            messages = messages + [
                HumanMessage(
                    f"Your previous answer could not be used: {error}. "
                    "Answer again, matching the requested schema exactly."
                )
            ]

    raise ExtractionFailed("; ".join(errors)[-2000:])
