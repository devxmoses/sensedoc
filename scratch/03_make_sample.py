import pymupdf

lines = [
    "ADEBAYO SUPPLIES LTD",
    "12 Marina Road, Lagos",
    "",
    "INVOICE",
    "Invoice No: INV-2026-0147",
    "Date: 14 October 2026",
    "Bill To: Sunrise Mart",
    "",
    "Item                          Qty  Unit Price      Amount",
    "Coca-Cola Original 50cl PET    24      500.00   12,000.00",
    "Fanta Orange 35cl Can          12      350.00    4,200.00",
    "Pepsi 1L PET                    6      800.00    4,800.00",
    "",
    "Subtotal:   21,000.00",
    "VAT (7.5%):  1,575.00",
    "TOTAL DUE:  NGN 22,575.00",
]

doc = pymupdf.open()  # a new, empty PDF
page = doc.new_page()  # add one A4 page

y = 72  # PDF units are points: 72 points = 1 inch from the top
for line in lines:
    page.insert_text((72, y), line, fontname="cour", fontsize=10)
    y += 16  # move down for the next line

doc.save("samples/invoice_001.pdf")
print("Saved samples/invoice_001.pdf")
