"""Generate SYNTHETIC sample receipts (images) + their mocked extractions (JSON).

Run:  python make_samples.py
All businesses, items and prices are invented.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)


def font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "DejaVuSansMono.ttf", "Courier New.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def draw_receipt(lines, width=42):
    f, fb = font(22), font(28)
    h = 60 + 34 * len(lines)
    img = Image.new("RGB", (620, h), (252, 250, 244))
    d = ImageDraw.Draw(img)
    y = 30
    for text, style in lines:
        if style == "title":
            w = d.textlength(text, font=fb)
            d.text(((620 - w) / 2, y), text, fill=(20, 20, 20), font=fb)
        elif style == "center":
            w = d.textlength(text, font=f)
            d.text(((620 - w) / 2, y), text, fill=(60, 60, 60), font=f)
        else:
            d.text((30, y), text, fill=(25, 25, 25), font=f)
        y += 34
    return img


def row(name, price, width=40):
    price = f"{price:.2f}"
    return (name + " " * max(1, width - len(name) - len(price)) + price, "row")


def save(name, img, extraction):
    img.save(OUT / f"{name}.png")
    (OUT / f"{name}.json").write_text(json.dumps(extraction, indent=2) + "\n")


# 1) Representative case: clean receipt, tip printed ---------------------------
items1 = [("Spicy Chicken Sandwich", 14.50), ("Mushroom Risotto", 18.00), ("Caesar Salad", 11.25),
          ("Truffle Fries", 9.00), ("Iced Tea x2", 7.00), ("Craft Beer", 8.50)]
lines = [("LULA'S KITCHEN", "title"), ("123 Maple St, Springfield", "center"),
         ("11/02/2026  7:41 PM   Table 12", "center"), ("-" * 40, "row")]
lines += [row(n, p) for n, p in items1]
lines += [("-" * 40, "row"), row("SUBTOTAL", 68.25), row("TAX 8.75%", 5.97), row("TIP", 13.65),
          row("TOTAL", 87.87), ("", "row"), ("VISA ****4821", "center"), ("Thank you!", "center")]
save("1_lulas_kitchen", draw_receipt(lines), {
    "is_receipt": True, "merchant": "Lula's Kitchen",
    "items": [{"name": "Spicy Chicken Sandwich", "quantity": 1, "price": 14.50},
              {"name": "Mushroom Risotto", "quantity": 1, "price": 18.00},
              {"name": "Caesar Salad", "quantity": 1, "price": 11.25},
              {"name": "Truffle Fries", "quantity": 1, "price": 9.00},
              {"name": "Iced Tea", "quantity": 2, "price": 7.00},
              {"name": "Craft Beer", "quantity": 1, "price": 8.50}],
    "subtotal": 68.25, "tax": 5.97, "tip": 13.65, "total": 87.87, "notes": ""})

# 2) Difficult case: blurry, tilted photo; AI misreads one price; no tip printed --
items2 = [("Kung Pao Chicken", 15.95), ("Beef Chow Fun", 16.50), ("Veg Dumplings (8)", 9.50),
          ("Hot & Sour Soup", 6.75), ("Jasmine Rice x3", 7.50)]
lines = [("GOLDEN WOK", "title"), ("88 Elm Ave", "center"), ("11/03/2026  6:15 PM", "center"), ("-" * 40, "row")]
lines += [row(n, p) for n, p in items2]
lines += [("-" * 40, "row"), row("SUBTOTAL", 56.20), row("TAX 10.25%", 5.76), row("TOTAL", 61.96),
          ("", "row"), ("Tip not included", "center")]
img = draw_receipt(lines).rotate(4, expand=True, fillcolor=(90, 80, 70)).filter(ImageFilter.GaussianBlur(1.6))
save("2_golden_wok_blurry", img, {
    "is_receipt": True, "merchant": "Golden Wok",
    "items": [{"name": "Kung Pao Chicken", "quantity": 1, "price": 15.95},
              {"name": "Beef Chow Fun", "quantity": 1, "price": 6.50},   # misread: real price 16.50
              {"name": "Veg Dumplings (8)", "quantity": 1, "price": 9.50},
              {"name": "Hot & Sour Soup", "quantity": 1, "price": 6.75},
              {"name": "Jasmine Rice", "quantity": 3, "price": 7.50}],
    "subtotal": 56.20, "tax": 5.76, "tip": None, "total": 61.96,
    "notes": "Photo is blurry and tilted; the price for Beef Chow Fun was hard to read."})

# 3) Invalid input: not a receipt at all ----------------------------------------
img = Image.new("RGB", (620, 460), (150, 200, 240))
d = ImageDraw.Draw(img)
d.ellipse((450, 40, 540, 130), fill=(255, 215, 80))
d.polygon([(0, 460), (180, 170), (360, 460)], fill=(90, 120, 90))
d.polygon([(200, 460), (420, 130), (620, 460)], fill=(70, 100, 75))
d.rectangle((0, 400, 620, 460), fill=(80, 150, 80))
save("3_not_a_receipt", img, {
    "is_receipt": False, "merchant": "", "items": [], "subtotal": None, "tax": None,
    "tip": None, "total": None, "notes": "The image shows a landscape, not a receipt."})

print("Wrote samples to", OUT)
