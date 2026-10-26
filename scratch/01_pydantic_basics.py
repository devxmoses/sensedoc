from datetime import date

from pydantic import BaseModel, Field, ValidationError


class Invoice(BaseModel):
    invoice_number: str
    invoice_date: date
    total_amount: float
    currency: str = "NGN"  # default value, so this field is optional
    vendor: str | None = None  # "str or None": may be missing
    notes: str = Field(default="", description="Any extra remarks")

raw = {
    "invoice_number": "INV-001",
    "invoice_date": "2026-10-25",  
    "total_amount": "15400.50", 
}
invoice = Invoice(**raw)
print(invoice)
print(type(invoice.invoice_date))  
print(invoice.total_amount + 100)  


bad = {
    "invoice_number": "INV-002",
    "invoice_date": "last tuesday",
    "total_amount": "about fifty",
}
try:
    Invoice(**bad)
except ValidationError as e:
    print("\nValidation failed:")
    print(e)
print("\nAs JSON:")
print(invoice.model_dump_json(indent=2))
