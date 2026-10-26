import os
from datetime import date

import pymupdf
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

load_dotenv()


# ---------- 1. The schema: what we want out ----------
class LineItem(BaseModel):
    description: str = Field(description="Product name exactly as written")
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = Field(None, description="Line total")


class Invoice(BaseModel):
    invoice_number: str | None = Field(None, description="Invoice ID, e.g. INV-123")
    invoice_date: date | None = Field(None, description="Date the invoice was issued")
    vendor: str | None = Field(None, description="Company that issued the invoice")
    customer: str | None = Field(None, description="Company being billed")
    currency: str | None = Field(None, description="ISO code, e.g. NGN, USD")
    subtotal: float | None = None
    tax: float | None = None
    total_amount: float | None = Field(None, description="Final amount due incl. tax")
    line_items: list[LineItem] = Field(default_factory=list)


# ---------- 2. Read the document ----------
def read_pdf_text(path: str) -> str:
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


# ---------- 3. The prompt ----------
prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You extract data from business documents. "
            "Only use information that appears in the document. "
            "If a field is not shown, return null. Never guess.",
        ),
        ("human", "Document text:\n\n{document}"),
    ]
)

# ---------- 4. The model + the chain ----------
llm = ChatGoogleGenerativeAI(model=os.environ["GEMINI_MODEL"], temperature=0)
chain = prompt | llm.with_structured_output(Invoice)

# ---------- 5. Run it ----------
text = read_pdf_text("samples/invoice_001.pdf")
print("----- RAW TEXT -----")
print(text)

result = chain.invoke({"document": text})

print("----- EXTRACTED -----")
print(result.model_dump_json(indent=2))

# ---------- 6. A first sanity check ----------
items_sum = sum(item.amount or 0 for item in result.line_items)
print(f"\nLine items add up to {items_sum:,.2f}; subtotal says {result.subtotal:,.2f}")
