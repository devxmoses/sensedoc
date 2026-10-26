from sensedoc.schema_builder import Template, TemplateField, build_model

template = Template(
    name="Mini Invoice",
    document_type="invoice",
    fields=[
        TemplateField(name="Invoice Number", type="text"),
        TemplateField(name="Total Amount", type="currency"),
        TemplateField(
            name="Items",
            type="table",
            columns=[
                TemplateField(name="Product"),
                TemplateField(name="Unit Price", type="currency"),
            ],
        ),
    ],
)

Model = build_model("Extraction", template.fields)

# The model works just like a hand-written class
data = Model(
    invoice_number="INV-9",
    total_amount="1500",
    items=[{"product": "Fanta 35cl", "unit_price": "350"}],
)
print(data)
print(data.items[0].unit_price + 50)  # it's a real number: 400.0
