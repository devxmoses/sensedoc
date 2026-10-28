"""Generate a labelled test set: documents plus the answers we expect.

Because we create the documents, we know every correct value. Hard cases are added on purpose:
tilted, blurred phone-style photos, look-alike product variants, a missing size, and a line
listing two sizes.

Run:  uv run python evaluation/make_dataset.py
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dataset"
DEMO = ROOT.parent / "samples" / "demo"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
random.seed(7)


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSansMono" if mono else "DejaVuSans"
    path = FONT_DIR / f"{name}{'-Bold' if bold else ''}.ttf"
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size)


def photo_effect(img: Image.Image, angle: float, blur: float) -> Image.Image:
    """Make a clean render look like a phone photo: tilted, soft, on a grey table."""
    img = img.convert("RGB").rotate(angle, expand=True, fillcolor=(205, 200, 190))
    return img.filter(ImageFilter.GaussianBlur(blur))


def money(x: float) -> str:
    return f"{x:,.2f}"


# ---------- Invoices: the same invoice as a digital PDF and as a photo ----------
SUPPLIERS = ["ADEBAYO SUPPLIES LTD", "LAKESIDE DRINKS DISTRIBUTION", "OKAFOR & SONS TRADING", "NORTHGATE WHOLESALE"]
CUSTOMERS = ["Sunrise Mart", "Corner Shop Ikeja", "Green Basket Stores", "Palmview Supermarket"]
ITEMS = [
    ("Coca-Cola Original 50cl PET", 500),
    ("Coke Zero 33cl Can", 450),
    ("Fanta Orange 35cl Can", 350),
    ("Sprite 50cl PET", 480),
    ("Pepsi 1L PET", 800),
    ("Coca-Cola 35cl Can x12", 5400),
    ("Diet Coke 33cl Can", 420),
]


def make_invoice(n: int) -> dict:
    items = []
    for name, price in random.sample(ITEMS, k=random.randint(2, 5)):
        qty = random.choice([6, 12, 24, 36, 48])
        items.append({"product": name, "quantity": qty, "unit_price": price, "line_total": qty * price})
    subtotal = sum(i["line_total"] for i in items)
    tax = round(subtotal * 0.075, 2)
    issued = date(2026, 9, 1) + timedelta(days=random.randint(0, 50))
    return {
        "invoice_number": f"INV-2026-{random.randint(1000, 9999)}",
        "invoice_date": issued.isoformat(),
        "supplier": SUPPLIERS[n % len(SUPPLIERS)],
        "subtotal": subtotal,
        "tax": tax,
        "total_amount": round(subtotal + tax, 2),
        "items": items,
        "_customer": CUSTOMERS[n % len(CUSTOMERS)],
    }


def render_invoice_pdf(inv: dict, path: Path) -> None:
    issued = date.fromisoformat(inv["invoice_date"])
    lines = [
        (inv["supplier"], 16, "hebo"),
        ("Plot 12, Industrial Avenue, Lagos", 9, "helv"),
        ("", 10, "helv"),
        ("INVOICE", 20, "hebo"),
        (f"Invoice No: {inv['invoice_number']}", 10, "helv"),
        (f"Date: {issued:%d %B %Y}", 10, "helv"),
        (f"Bill To: {inv['_customer']}", 10, "helv"),
        ("", 10, "helv"),
        (f"{'Item':<32}{'Qty':>5}{'Unit Price':>14}{'Amount':>14}", 10, "cobo"),
    ]
    for i in inv["items"]:
        lines.append((f"{i['product']:<32}{i['quantity']:>5}{money(i['unit_price']):>14}{money(i['line_total']):>14}", 10, "cour"))
    lines += [
        ("", 10, "helv"),
        (f"{'Subtotal:':<20}{money(inv['subtotal']):>16}", 10, "cour"),
        (f"{'VAT (7.5%):':<20}{money(inv['tax']):>16}", 10, "cour"),
        (f"{'TOTAL DUE:':<20}{'NGN ' + money(inv['total_amount']):>16}", 11, "cobo"),
        ("", 10, "helv"),
        ("Payment within 30 days. Thank you for your business.", 8, "helv"),
    ]
    doc = pymupdf.open()
    page = doc.new_page()
    y = 70
    for text, size, fontname in lines:
        page.insert_text((60, y), text, fontname=fontname, fontsize=size)
        y += size + 8
    doc.save(path)


def pdf_to_photo(pdf_path: Path, png_path: Path) -> None:
    with pymupdf.open(pdf_path) as pdf:
        pix = pdf[0].get_pixmap(dpi=130)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    photo_effect(img, angle=random.uniform(-4, 4), blur=0.8).save(png_path)


# ---------- Receipts: narrow till slips, photographed ----------
STORES = ["SHOPRITE LEKKI", "SPAR VICTORIA ISLAND", "JUSTRITE IKORODU"]
RECEIPT_ITEMS = [("COKE 50CL", 500), ("BREAD LOAF", 1200), ("PEAK MILK 400G", 2800), ("INDOMIE X5", 1500),
                 ("FANTA 35CL", 350), ("EGGS 12", 2400), ("RICE 1KG", 1900)]


def make_receipt(n: int, path: Path) -> dict:
    items = []
    for name, price in random.sample(RECEIPT_ITEMS, k=random.randint(3, 5)):
        qty = random.randint(1, 3)
        items.append({"product": name, "quantity": qty, "line_total": qty * price})
    total = sum(i["line_total"] for i in items)
    bought = date(2026, 10, 1) + timedelta(days=random.randint(0, 24))
    truth = {
        "store_name": STORES[n % len(STORES)],
        "receipt_date": bought.isoformat(),
        "receipt_number": f"{random.randint(100000, 999999)}",
        "total_amount": total,
        "payment_method": random.choice(["CASH", "CARD", "TRANSFER"]),
        "items": items,
    }
    img = Image.new("RGB", (460, 120 + 34 * (len(items) + 9)), "white")
    d = ImageDraw.Draw(img)
    mono, big = font(18, mono=True), font(22, bold=True, mono=True)
    y = 20
    d.text((230, y), truth["store_name"], font=big, fill="black", anchor="mt")
    y += 44
    for line in [f"DATE: {bought:%d/%m/%Y}", f"RECEIPT NO: {truth['receipt_number']}", "-" * 34]:
        d.text((20, y), line, font=mono, fill="black")
        y += 30
    for i in items:
        d.text((20, y), f"{i['quantity']} x {i['product']}", font=mono, fill="black")
        d.text((440, y), money(i["line_total"]), font=mono, fill="black", anchor="ra")
        y += 30
    d.text((20, y), "-" * 34, font=mono, fill="black")
    y += 30
    d.text((20, y), "TOTAL", font=big, fill="black")
    d.text((440, y), f"N{money(total)}", font=big, fill="black", anchor="ra")
    y += 40
    d.text((20, y), f"PAID BY: {truth['payment_method']}", font=mono, fill="black")
    d.text((230, y + 40), "THANK YOU FOR SHOPPING", font=mono, fill="black", anchor="mt")
    photo_effect(img, angle=random.uniform(-3, 3), blur=0.6).save(path)
    return truth


# ---------- Leaflets: the variant-matching traps from the plan ----------
COLOURS = {"red": (200, 16, 30), "black": (25, 25, 25), "silver": (185, 190, 196), "orange": (245, 130, 20),
           "green": (20, 150, 70), "blue": (20, 70, 170)}

LEAFLETS = {
    "leaflet_01": {
        "store": "SUNRISE MART",
        "valid": "20 Oct 2026",
        "tiles": [
            # (label, price text, shape, colour, expected rows: (sku or None for "must go to review", price))
            ("Coca-Cola 50cl", "₦500", "bottle", "red", [("CC-ORIG-500-PET", 500)]),
            ("Coke Zero Can", "₦450", "can", "black", [(None, 450)]),
            ("Coca-Cola 35cl\n12 cans", "₦5,400", "pack", "red", [("CC-ORIG-350-CAN-12", 5400)]),
            ("Coke 35cl Can", "₦300", "can", "red", [("CC-ORIG-350-CAN", 300)]),
            ("Coke Zero 50cl", "₦520", "bottle", "black", [("CC-ZERO-500-PET", 520)]),
            ("Fanta Orange 35cl", "₦350", "can", "orange", [("FANTA-ORA-350-CAN", 350)]),
        ],
    },
    "leaflet_02": {
        "store": "GREEN BASKET STORES",
        "valid": "22 Oct 2026",
        "tiles": [
            ("Coke", "₦400", "bottle", "red", [(None, 400)]),
            ("Diet Coke 33cl", "₦420", "can", "silver", [("CC-DIET-330-CAN", 420)]),
            ("Sprite 50cl", "₦480", "bottle", "green", [("SPRITE-500-PET", 480)]),
            ("Pepsi 1L", "₦800", "bottle", "blue", [("PEPSI-ORIG-1000-PET", 800)]),
            ("Coca-Cola cans\n33cl / 35cl", "₦280 / ₦300", "can", "red", [("CC-ORIG-330-CAN", 280), ("CC-ORIG-350-CAN", 300)]),
            ("Fanta Orange 35cl\n12-pack", "₦4,000", "pack", "orange", [("FANTA-ORA-350-CAN-12", 4000)]),
        ],
    },
}


def draw_pack(d: ImageDraw.ImageDraw, x: int, y: int, shape: str, colour: str) -> None:
    c = COLOURS[colour]
    if shape == "bottle":
        d.rounded_rectangle((x + 40, y + 50, x + 110, y + 230), 22, fill=c)
        d.rectangle((x + 62, y + 10, x + 88, y + 55), fill=c)
        d.rectangle((x + 58, y, x + 92, y + 12), fill=(60, 60, 60))
        d.rectangle((x + 40, y + 120, x + 110, y + 160), fill="white")
    elif shape == "can":
        d.rounded_rectangle((x + 35, y + 70, x + 115, y + 230), 10, fill=c)
        d.rectangle((x + 35, y + 130, x + 115, y + 160), fill="white")
    else:  # pack of cans
        for i in range(4):
            d.rounded_rectangle((x + i * 34, y + 110, x + i * 34 + 30, y + 230), 6, fill=c)
        d.rectangle((x - 4, y + 150, x + 140, y + 190), fill=(240, 240, 240), outline=c, width=3)


def make_leaflet(name: str, spec: dict, path: Path) -> dict:
    img = Image.new("RGB", (1200, 1500), (255, 248, 225))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1200, 170), fill=(200, 16, 30))
    d.text((600, 50), spec["store"], font=font(56, bold=True), fill="white", anchor="mt")
    d.text((600, 120), f"DRINKS DEALS  ·  Prices valid from {spec['valid']}", font=font(26), fill="white", anchor="mt")
    rows = []
    for i, (label, price, shape, colour, expected) in enumerate(spec["tiles"]):
        col, row = i % 3, i // 3
        x, y = 40 + col * 380, 210 + row * 640
        d.rounded_rectangle((x, y, x + 350, y + 600), 24, fill="white", outline=(230, 220, 200), width=3)
        draw_pack(d, x + 100, y + 30, shape, colour)
        d.multiline_text((x + 175, y + 300), label, font=font(30, bold=True), fill=(30, 30, 30), anchor="ma", align="center")
        d.ellipse((x + 75, y + 400, x + 275, y + 580), fill=(255, 210, 0))
        d.text((x + 175, y + 490), price, font=font(40 if "/" not in price else 26, bold=True), fill=(200, 16, 30), anchor="mm")
        rows += [{"product_text": label.replace("\n", " "), "sku": sku, "price": p} for sku, p in expected]
    photo_effect(img, angle=random.uniform(-2, 2), blur=0.5).save(path)
    return {"store_name": spec["store"], "products": rows}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DEMO.mkdir(parents=True, exist_ok=True)
    cases = []

    for n in range(6):
        inv = make_invoice(n)
        pdf, png = OUT / f"invoice_{n:02d}.pdf", OUT / f"invoice_{n:02d}_photo.png"
        render_invoice_pdf(inv, pdf)
        pdf_to_photo(pdf, png)
        truth = {k: v for k, v in inv.items() if not k.startswith("_")}
        cases.append({"file": pdf.name, "template": "invoice", "route": "text", "pair": n, "expected": truth})
        cases.append({"file": png.name, "template": "invoice", "route": "vision", "pair": n, "expected": truth})

    for n in range(3):
        png = OUT / f"receipt_{n:02d}.png"
        cases.append({"file": png.name, "template": "receipt", "route": "vision", "expected": make_receipt(n, png)})

    for name, spec in LEAFLETS.items():
        png = OUT / f"{name}.png"
        cases.append({"file": png.name, "template": "price_list", "route": "vision", "expected": make_leaflet(name, spec, png)})

    (OUT / "labels.json").write_text(json.dumps(cases, indent=2))

    # a few of them double as demo files for the app
    for f in ["invoice_00.pdf", "invoice_01_photo.png", "receipt_00.png", "leaflet_01.png", "leaflet_02.png"]:
        (DEMO / f).write_bytes((OUT / f).read_bytes())
    print(f"{len(cases)} labelled documents in {OUT}; demo files in {DEMO}")


if __name__ == "__main__":
    main()
