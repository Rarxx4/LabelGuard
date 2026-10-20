"""Generates the demo sample set in ./samples.

  artwork_v1_masala_peanuts.pdf        artwork with 7 planted errors
  artwork_v1_masala_peanuts.png        raster copy of v1 (exercises the OCR path)
  artwork_v2_masala_peanuts_fixed.pdf  corrected artwork
  rulebook_snacks_india.pdf            company rulebook interpreting FSSAI rules
  approved_product_spec.xlsx           approved product information

Planted errors in v1 (the "answer key" for the demo):
  1. Net quantity 150 g, approved 200 g                          (LBL-01/02 + spec)
  2. Net quantity numerals ~2.3 mm, rule needs >= 4 mm            (LBL-02)
  3. Ingredients say Peanuts (70%), approved 72%                 (LBL-03)
  4. No "Contains: Peanuts" - only a "May contain" line          (LBL-04)
  5. Sodium 610 mg, approved 560 mg                              (LBL-05)
  6. Licence number has 13 digits / does not match               (LBL-07)
  7. "HIGH PROTEIN" with 18.5 g protein + "Boosts Immunity!"     (CLM-01/02/03)

Product, company and licence numbers are fictitious.
Run:  python scripts/make_samples.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import labelguard  # noqa: E402,F401  (Windows C++ runtime fix must run before pymupdf loads)
import pymupdf as fitz  # noqa: E402
from openpyxl import Workbook
from openpyxl.styles import Font

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)


def mm(v):
    return v * 72 / 25.4


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


APPROVED = {
    "product_name": "Masala Crunch Peanuts",
    "brand": "Crunchwell",
    "descriptor": "Roasted & Spiced Peanut Snack",
    "net_quantity": "200 g",
    "ingredients": "Peanuts (72%), Gram Flour (Besan), Edible Vegetable Oil (Palmolein), Spices & Condiments "
                   "(Red Chilli, Turmeric, Coriander, Cumin), Iodised Salt, Curry Leaves (1%), Black Salt, "
                   "Acidity Regulator (INS 330)",
    "contains": "Peanuts",
    "may_contain": "Gluten",
    "veg": "Vegetarian (green symbol)",
    "licence": "10012345000678",
    "mrp": "Rs. 60.00 (Incl. of all taxes)",
    "shelf_life": "Best Before 6 months from manufacture",
    "storage": "Store in a cool, dry place. Once opened, transfer contents to an airtight container.",
    "manufacturer": "Crunchwell Foods Pvt. Ltd., Plot 42, MIDC Industrial Area, Chakan, Pune, "
                    "Maharashtra - 410501, India",
    "customer_care": "1800-123-4567 | care@crunchwell.in",
    "claims": "Source of Protein",
    "nutrition": [("Energy", "560", "kcal"), ("Protein", "18.5", "g"), ("Carbohydrate", "30.2", "g"),
                  ("Total Sugars", "2.1", "g"), ("Added Sugars", "0", "g"), ("Total Fat", "40.5", "g"),
                  ("Saturated Fat", "7.8", "g"), ("Trans Fat", "0.1", "g"), ("Sodium", "560", "mg")],
}

VARIANTS = {
    "v1": dict(file="artwork_v1_masala_peanuts.pdf", net="Net Wt. 150 g", net_size=9, claim="HIGH PROTEIN",
               extra_claim="Boosts Immunity!",
               ingredients=APPROVED["ingredients"].replace("Peanuts (72%)", "Peanuts (70%)"),
               allergen="May contain traces of gluten.", licence="Lic. No. 1001234500067", sodium="610"),
    "v2": dict(file="artwork_v2_masala_peanuts_fixed.pdf", net="Net Wt. 200 g", net_size=16,
               claim="SOURCE OF PROTEIN", extra_claim=None, ingredients=APPROVED["ingredients"],
               allergen="Contains: Peanuts. May contain traces of gluten.", licence="Lic. No. 10012345000678",
               sodium="560"),
}


def text(page, x, y, s, size, bold=False, color="#222222"):
    """y is the top of the text line."""
    page.insert_text((x, y + size * 0.8), s, fontsize=size, fontname="hebo" if bold else "helv", color=rgb(color))


def box(page, x, y, w, h, s, size, bold=False, color="#222222", align=0):
    rect = fitz.Rect(x, y, x + w, y + h)
    rest = page.insert_textbox(rect, s, fontsize=size, fontname="hebo" if bold else "helv", color=rgb(color),
                               align=align)
    assert rest >= 0, f"text overflow: {s[:40]}"
    return h - rest


def draw_artwork(v):
    doc = fitz.open()
    page = doc.new_page(width=mm(330), height=mm(170))
    fx, fy, fw, fh = mm(10), mm(10), mm(140), mm(150)
    bx0, by0, bw0, bh0 = mm(160), mm(10), mm(160), mm(150)
    page.draw_rect(fitz.Rect(fx, fy, fx + fw, fy + fh), fill=rgb("#f6c445"), color=rgb("#d0021b"),
                   width=0.6, dashes="[4 3] 0")
    page.draw_rect(fitz.Rect(bx0, by0, bx0 + bw0, by0 + bh0), fill=rgb("#fff8e6"), color=rgb("#d0021b"),
                   width=0.6, dashes="[4 3] 0")
    text(page, fx, mm(4), "FRONT PANEL (PDP)", 6, color="#888888")
    text(page, bx0, mm(4), "BACK PANEL", 6, color="#888888")

    # ---- front ----
    x = fx + mm(8)
    text(page, x, fy + mm(12), "CRUNCHWELL", 30, True, "#7a1f00")
    text(page, x, fy + mm(30), "Masala Crunch", 22, True, "#2b1700")
    text(page, x, fy + mm(39), "Peanuts", 22, True, "#2b1700")
    text(page, x, fy + mm(50), APPROVED["descriptor"], 11, color="#2b1700")
    vx, vy = fx + fw - mm(20), fy + mm(8)  # vegetarian symbol
    page.draw_rect(fitz.Rect(vx, vy, vx + mm(10), vy + mm(10)), color=rgb("#0a8a2a"), width=1.6)
    page.draw_circle((vx + mm(5), vy + mm(5)), mm(3), color=rgb("#0a8a2a"), fill=rgb("#0a8a2a"))
    page.draw_rect(fitz.Rect(x, fy + mm(63), x + mm(62), fy + mm(75)), color=rgb("#c0392b"),
                   fill=rgb("#c0392b"), radius=0.25)
    box(page, x, fy + mm(65.5), mm(62), mm(9), v["claim"], 14, True, "#ffffff", align=1)
    if v["extra_claim"]:
        text(page, x, fy + mm(81), v["extra_claim"], 13, True, "#0b5e2a")
    for i in range(9):  # product visual
        cx, cy = fx + mm(80) + (i % 3) * mm(14), fy + mm(92) + (i // 3) * mm(11)
        page.draw_oval(fitz.Rect(cx - mm(6), cy - mm(4), cx + mm(6), cy + mm(4)),
                       fill=rgb("#b5651d" if i % 2 else "#a0522d"), color=None)
    text(page, x, fy + fh - mm(16), v["net"], v["net_size"], True, "#2b1700")

    # ---- back ----
    bx, bw = bx0 + mm(6), bw0 - mm(12)
    y = by0 + mm(6)
    text(page, bx, y, "INGREDIENTS:", 8, True)
    y += mm(4)
    y += box(page, bx, y, bw, mm(20), v["ingredients"] + ".", 7) + mm(2)
    y += box(page, bx, y, bw, mm(8), v["allergen"], 7, True) + mm(3)

    tw, rh = mm(80), mm(4.6)  # nutrition table
    page.draw_rect(fitz.Rect(bx, y, bx + tw, y + rh * 11), color=rgb("#222222"), width=0.5)
    text(page, bx + mm(2), y + mm(1.2), "NUTRITIONAL INFORMATION (Approx.)", 7, True)
    text(page, bx + tw - mm(20), y + rh + mm(1.2), "Per 100 g", 7, True)
    for i, (name, val, unit) in enumerate(APPROVED["nutrition"]):
        ry = y + rh * (i + 2)
        page.draw_line((bx, ry), (bx + tw, ry), color=rgb("#222222"), width=0.5)
        indent = mm(4) if name in ("Total Sugars", "Added Sugars", "Saturated Fat", "Trans Fat") else 0
        text(page, bx + mm(2) + indent, ry + mm(1.2), f"{name} ({unit})", 7)
        text(page, bx + tw - mm(20), ry + mm(1.2), v["sodium"] if name == "Sodium" else val, 7)

    rx, rw = bx + tw + mm(6), bw - tw - mm(6)
    ry = y
    text(page, rx, ry, "STORAGE:", 7, True)
    box(page, rx, ry + mm(3.5), rw, mm(12), APPROVED["storage"], 7)
    ry += mm(17)
    box(page, rx, ry, rw, mm(8), APPROVED["shelf_life"] + ".", 7, True)
    box(page, rx, ry + mm(8), rw, mm(8), "Batch No.: / Mfg. Date: See crimp", 7)
    ry += mm(19)
    box(page, rx, ry, rw, mm(10), "MRP " + APPROVED["mrp"], 9, True)

    y += rh * 11 + mm(5)
    text(page, bx, y, "Manufactured & Marketed by:", 7, True)
    box(page, bx, y + mm(3.5), mm(95), mm(8), APPROVED["manufacturer"], 7)
    box(page, bx, y + mm(11), mm(95), mm(5), "Customer Care: " + APPROVED["customer_care"], 7)

    lx = bx + mm(100)  # FSSAI logo + licence
    page.draw_rect(fitz.Rect(lx, y, lx + mm(18), y + mm(8)), color=rgb("#1f4e9c"), width=0.8)
    text(page, lx + mm(3), y + mm(2), "fssai", 10, True, "#1f4e9c")
    text(page, lx, y + mm(10), v["licence"], 7)
    for i in range(40):  # barcode
        if (i * 7) % 3 == 0:
            continue
        x0 = lx + i * mm(0.9)
        page.draw_rect(fitz.Rect(x0, y + mm(16), x0 + mm(0.6 if i % 4 == 0 else 0.35), y + mm(26)),
                       fill=(0, 0, 0), color=None)
    text(page, lx, y + mm(27), "8 901234 567890", 6, color="#000000")
    doc.set_metadata({"title": f"Artwork {v['file']}"})
    doc.save(OUT / v["file"])
    return doc


def draw_rulebook():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    margin, y = 56, 56

    def para(s, size=10, bold=False, gap=6):
        nonlocal page, y
        rect = fitz.Rect(margin, y, 595 - margin, 842 - margin)
        rest = page.insert_textbox(rect, s, fontsize=size, fontname="hebo" if bold else "helv")
        if rest < 0:
            page = doc.new_page(width=595, height=842)
            y = 56
            return para(s, size, bold, gap)
        y += rect.height - rest + gap

    para("Crunchwell Foods - Packaging Labelling Rulebook", 16, True)
    para("Category: Packaged Snack Foods | Market: India | Version 2.1", 10)
    para("Purpose: This rulebook describes how Crunchwell interprets the Food Safety and Standards (Labelling "
         "and Display) Regulations, 2020 (FSSAI) and our own brand standards. Every artwork must comply with every "
         "applicable rule below before it is released to print. Where the regulation and this rulebook differ, the "
         "stricter requirement applies. (Illustrative document prepared for the Esko AIForge hackathon - not "
         "legal advice.)")
    para("Section A - Mandatory declarations", 12, True)
    rules_a = [
        "LBL-01 Name of the food: The name of the food must appear on the front panel (principal display panel) "
        "and must match the approved product name exactly.",
        "LBL-02 Net quantity: The net quantity must be declared on the front panel in metric units (g or kg) and "
        "must match the approved net quantity. The numerals of the net quantity declaration must be at least 4 mm "
        "high.",
        "LBL-03 List of ingredients: The ingredients must be listed under the heading \"Ingredients\" in "
        "descending order of weight. The list must match the approved formulation, including the declared "
        "percentage of characterising ingredients (QUID).",
        "LBL-04 Allergen declaration: Allergens present in the product must be declared in a separate "
        "\"Contains:\" statement immediately after the ingredient list (for example \"Contains: Peanuts\"). A "
        "\"May contain\" statement covers cross-contact only and does not replace the \"Contains:\" statement.",
        "LBL-05 Nutritional information: Nutrition information must be given per 100 g and must include Energy "
        "(kcal), Protein, Carbohydrate, Total Sugars, Added Sugars, Total Fat, Saturated Fat, Trans Fat and Sodium "
        "(mg). All values must match the approved nutrition data.",
        "LBL-06 Veg / Non-veg symbol: Vegetarian products must carry the green vegetarian symbol (a green square "
        "outline containing a filled green circle) on the front panel, close to the name of the food.",
        "LBL-07 FSSAI logo and licence: The FSSAI logo and the 14-digit FSSAI licence number of the brand owner "
        "must be displayed. The licence number must match the approved licence number.",
        "LBL-08 Manufacturer address: The name and complete address of the manufacturer, including the PIN code, "
        "must be declared.",
        "LBL-09 Maximum retail price: The MRP must be declared as \"MRP Rs.\" (or the Rupee symbol) followed by "
        "the amount and the words \"Incl. of all taxes\".",
        "LBL-10 Date marking: The pack must declare a \"Best Before\" or \"Use By\" statement, and provide space "
        "for the batch number and the date of manufacture.",
        "LBL-11 Consumer care: A consumer care telephone number and e-mail address must be printed.",
        "LBL-12 Storage instructions: Storage instructions must be printed for products whose shelf life depends "
        "on storage conditions.",
    ]
    for r in rules_a:
        para(r)
    para("Section B - Claims (brand and regulatory)", 12, True)
    for r in [
        "CLM-01 Approved claims only: Only claims listed as approved in the product specification may appear on "
        "the pack.",
        "CLM-02 Protein claims: \"Source of protein\" requires at least 10 g protein per 100 g. \"High protein\" "
        "requires at least 20 g protein per 100 g.",
        "CLM-03 Health claims: Claims that a food prevents, treats or cures a disease, or boosts immunity, are "
        "prohibited on snack products.",
    ]:
        para(r)
    para("Section C - Design standards", 12, True)
    para("DSN-01 Brand logo: The Crunchwell brand name must appear on the front panel.")
    para("DSN-02 Legibility: Mandatory information on the back panel must not be smaller than 1.0 mm x-height.")
    doc.save(OUT / "rulebook_snacks_india.pdf")


def write_spec():
    wb = Workbook()
    s = wb.active
    s.title = "Product Spec"
    s.append(["Field", "Approved value"])
    for row in [
        ("Product name", APPROVED["product_name"]), ("Brand", APPROVED["brand"]),
        ("Descriptor", APPROVED["descriptor"]), ("Net quantity", APPROVED["net_quantity"]),
        ("Ingredients", APPROVED["ingredients"]), ("Allergens - Contains", APPROVED["contains"]),
        ("Allergens - May contain (cross-contact)", APPROVED["may_contain"]), ("Veg / Non-veg", APPROVED["veg"]),
        ("FSSAI licence number", APPROVED["licence"]), ("MRP", APPROVED["mrp"]),
        ("Shelf life", APPROVED["shelf_life"]), ("Storage", APPROVED["storage"]),
        ("Manufacturer", APPROVED["manufacturer"]), ("Customer care", APPROVED["customer_care"]),
        ("Approved claims", APPROVED["claims"]), ("Target market", "India"),
    ]:
        s.append(row)
    s["A1"].font = s["B1"].font = Font(bold=True)
    s.column_dimensions["A"].width, s.column_dimensions["B"].width = 36, 110
    n = wb.create_sheet("Nutrition per 100g")
    n.append(["Nutrient", "Value", "Unit"])
    for name, val, unit in APPROVED["nutrition"]:
        n.append([name, float(val), unit])
    wb.save(OUT / "approved_product_spec.xlsx")


if __name__ == "__main__":
    v1 = draw_artwork(VARIANTS["v1"])
    draw_artwork(VARIANTS["v2"])
    draw_rulebook()
    write_spec()
    pix = v1[0].get_pixmap(dpi=180)
    pix.save(OUT / "artwork_v1_masala_peanuts.png")
    for f in sorted(OUT.iterdir()):
        print(" -", f.name)
