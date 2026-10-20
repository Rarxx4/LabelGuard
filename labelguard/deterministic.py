"""Deterministic cross-checks - plain Python, no AI.

Compares what is printed on the artwork with the approved product spec
(quantities, ingredient lists, nutrition values, licence numbers, claims...)
and measures text sizes from the PDF text layer.

These results are given to the AI as facts, and the trust layer uses them to
catch the AI when it disagrees with arithmetic.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz, process

from .grounding import TextIndex, numbers
from .schemas import ArtworkReading, DeterministicCheck, LabelFacts, TextLine

QTY_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|kgs|kilograms?|g|gm|gms|grams?|mg|l|ltr|litres?|liters?|ml|cl)\b", re.I)
UNIT_FACTOR = {"kg": 1000, "kgs": 1000, "kilogram": 1000, "kilograms": 1000, "g": 1, "gm": 1, "gms": 1,
               "gram": 1, "grams": 1, "mg": 0.001, "l": 1000, "ltr": 1000, "litre": 1000, "litres": 1000,
               "liter": 1000, "liters": 1000, "ml": 1, "cl": 10}
PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
X_HEIGHT_RATIO = 0.52  # x-height of typical sans fonts relative to the em size


def words(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%. ]", " ", (s or "").lower())).strip()


def parse_quantity(s: str | None) -> float | None:
    m = QTY_RE.search(s or "")
    if not m:
        return None
    return float(m.group(1).replace(",", ".")) * UNIT_FACTOR[m.group(2).lower()]


def split_ingredients(s: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    s = re.sub(r"^\s*ingredients?\s*:?", "", s or "", flags=re.I).strip().rstrip(".")
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return [p for p in parts if p]


def ingredient_key(item: str) -> str:
    return words(item.split("(")[0])


def ingredient_pct(item: str) -> str | None:
    m = PCT_RE.search(item)
    return m.group(1).replace(",", ".") if m else None


class Checker:
    def __init__(self, spec: LabelFacts | None, reading: ArtworkReading, index: TextIndex):
        self.spec, self.art, self.index = spec, reading.facts, index
        self.reading = reading
        self.out: list[DeterministicCheck] = []

    def add(self, topic, status, expected="", found="", detail="", quote="", match=None):
        verified = True
        if quote:
            m = match if match is not None else self.index.locate(quote)
            verified = bool(m and m.verified)
            if m and m.verified:
                quote = m.text  # show the text exactly as found on the artwork
            if not verified:
                detail = (detail + " " if detail else "") + "(AI transcription of this text could not be confirmed " \
                                                            "in the text layer/OCR.)"
        self.out.append(DeterministicCheck(check_id=f"D{len(self.out) + 1}", topic=topic, status=status,
                                           expected=expected, found=found, detail=detail, artwork_quote=quote,
                                           artwork_verified=verified))

    # ------------------------------------------------------------------
    def run(self) -> list[DeterministicCheck]:
        if self.spec:
            self.text_field("product_name", "Product name")
            self.text_field("brand", "Brand")
            self.net_quantity()
            self.ingredients()
            self.allergens()
            self.nutrition()
            self.licence()
            self.text_field("mrp", "MRP", numeric=True)
            self.text_field("manufacturer", "Manufacturer name/address", numeric=True)
            self.text_field("customer_care", "Customer care", numeric=True)
            self.text_field("storage", "Storage instructions")
            self.text_field("date_marking", "Date marking / shelf life", numeric=True)
            self.claims()
        self.measurements()
        return self.out

    def text_field(self, field, label, numeric=False):
        exp, got = getattr(self.spec, field), getattr(self.art, field)
        if not exp:
            return
        if not got:
            self.add(label, "not_found", exp, "", f"{label} from the approved spec was not identified on the artwork.")
            return
        # Approved text contained in a longer printed block (e.g. followed by "Batch No.: ...") is a match.
        score = max(fuzz.token_set_ratio(words(exp), words(got)), fuzz.partial_ratio(words(exp), words(got))
                    if len(words(exp)) >= 12 else 0)
        nums_ok = not numeric or set(numbers(exp)) <= set(numbers(got))
        if score >= 90 and nums_ok:
            self.add(label, "match", exp, got, f"Similarity {score:.0f}/100.", quote=got)
        else:
            why = "numbers differ" if not nums_ok else f"text similarity only {score:.0f}/100"
            self.add(label, "mismatch", exp, got, f"Artwork differs from approved spec ({why}).", quote=got)

    def net_quantity(self):
        exp, got = self.spec.net_quantity, self.art.net_quantity
        if not exp:
            return
        if not got:
            self.add("Net quantity", "not_found", exp, "", "No net quantity identified on the artwork.")
            return
        e, g = parse_quantity(exp), parse_quantity(got)
        if e is None or g is None:
            self.add("Net quantity", "info", exp, got, "Could not parse the quantity for comparison.", quote=got)
        elif abs(e - g) < 1e-6:
            self.add("Net quantity", "match", exp, got, "Same quantity after unit conversion.", quote=got)
        else:
            self.add("Net quantity", "mismatch", exp, got,
                     f"Approved {e:g} vs printed {g:g} (base units).", quote=got)

    def ingredients(self):
        exp, got = self.spec.ingredients, self.art.ingredients
        if not exp:
            return
        if not got:
            self.add("Ingredients", "not_found", exp, "", "No ingredient list identified on the artwork.")
            return
        e_items, g_items = split_ingredients(exp), split_ingredients(got)
        e_map = {ingredient_key(i): i for i in e_items}
        g_map = {ingredient_key(i): i for i in g_items}
        problems = []
        for k, item in e_map.items():
            hit = process.extractOne(k, list(g_map), scorer=fuzz.ratio, score_cutoff=85)
            if not hit:
                problems.append(f"missing '{item}'")
                continue
            g_item = g_map[hit[0]]
            pe, pg = ingredient_pct(item), ingredient_pct(g_item)
            if pe != pg:
                problems.append(f"'{item.split('(')[0].strip()}' percentage {pe or 'none'}% approved vs "
                                f"{pg or 'none'}% printed")
        for k, item in g_map.items():
            if not process.extractOne(k, list(e_map), scorer=fuzz.ratio, score_cutoff=85):
                problems.append(f"extra '{item}' not in approved formulation")
        e_order = [k for k in e_map if process.extractOne(k, list(g_map), scorer=fuzz.ratio, score_cutoff=85)]
        g_order = [process.extractOne(k, e_order, scorer=fuzz.ratio, score_cutoff=85)[0]
                   for k in g_map if process.extractOne(k, e_order, scorer=fuzz.ratio, score_cutoff=85)]
        if e_order != g_order:
            problems.append("ingredient order differs from the approved formulation")
        if problems:
            self.add("Ingredients", "mismatch", exp, got, "; ".join(problems) + ".", quote=got)
        else:
            self.add("Ingredients", "match", exp, got,
                     f"All {len(e_items)} ingredients, order and percentages match.", quote=got)

    def allergens(self):
        for field, label in (("allergens_contains", "Allergens (Contains)"),
                             ("allergens_may_contain", "Allergens (May contain)")):
            exp = {words(a) for a in getattr(self.spec, field)}
            got = {words(a) for a in getattr(self.art, field)}
            if not exp and not got:
                continue
            missing = {a for a in exp if not any(fuzz.partial_ratio(a, g) >= 85 for g in got)}
            if missing:
                self.add(label, "mismatch" if got else "not_found", ", ".join(sorted(exp)), ", ".join(sorted(got)),
                         f"Not declared on artwork: {', '.join(sorted(missing))}.",
                         quote=self.art.allergen_statement or "")
            else:
                self.add(label, "match", ", ".join(sorted(exp)), ", ".join(sorted(got)),
                         "All approved allergens declared.", quote=self.art.allergen_statement or "")

    def nutrition(self):
        if not self.spec.nutrition:
            return
        if not self.art.nutrition:
            self.add("Nutrition table", "not_found", f"{len(self.spec.nutrition)} nutrients", "",
                     "No nutrition table identified on the artwork.")
            return
        art = {words(r.nutrient): r for r in self.art.nutrition}
        for row in self.spec.nutrition:
            hit = process.extractOne(words(row.nutrient), list(art), scorer=fuzz.token_sort_ratio, score_cutoff=85)
            label = f"Nutrition: {row.nutrient}"
            exp = f"{row.value} {row.unit}"
            if not hit:
                self.add(label, "not_found", exp, "", f"{row.nutrient} not found in the artwork nutrition table.")
                continue
            a = art[hit[0]]
            got = f"{a.value} {a.unit}"
            try:
                ev, gv = float(row.value.replace(",", ".")), float(a.value.replace(",", "."))
                same = abs(ev - gv) <= max(0.005 * abs(ev), 1e-9)
            except ValueError:
                same = words(row.value) == words(a.value)
            unit_ok = words(row.unit) == words(a.unit) or not a.unit
            quote = f"{a.nutrient} {a.value}"
            m = self.index.locate_row(a.nutrient, a.value) or False
            if same and unit_ok:
                self.add(label, "match", exp, got, quote=quote, match=m)
            else:
                self.add(label, "mismatch", exp, got, "Value or unit differs from approved nutrition data.",
                         quote=quote, match=m)

    def licence(self):
        exp = ["".join(numbers(x)) for x in self.spec.licence_numbers]
        got = ["".join(re.findall(r"\d", x)) for x in self.art.licence_numbers]
        if not exp:
            return
        if not got:
            self.add("Licence number", "not_found", ", ".join(exp), "", "No licence number identified on artwork.")
            return
        for e in exp:
            if e in got:
                self.add("Licence number", "match", e, e, f"{len(e)} digits, identical.",
                         quote=self.art.licence_numbers[got.index(e)])
            else:
                g = got[0]
                self.add("Licence number", "mismatch", e, g,
                         f"Approved has {len(e)} digits, printed has {len(g)} digits.",
                         quote=self.art.licence_numbers[0])

    def claims(self):
        approved = [words(c) for c in self.spec.claims]
        for claim in self.art.claims:
            ok = approved and process.extractOne(words(claim), approved, scorer=fuzz.token_set_ratio,
                                                 score_cutoff=85)
            if not approved:
                self.add(f"Claim: {claim}", "info", "", claim, "Spec lists no approved claims.", quote=claim)
            elif ok:
                self.add(f"Claim: {claim}", "match", ", ".join(self.spec.claims), claim, "Claim is approved.",
                         quote=claim)
            else:
                self.add(f"Claim: {claim}", "mismatch", ", ".join(self.spec.claims), claim,
                         "Claim is not in the approved claims list.", quote=claim)

    def measurements(self):
        """Physical text sizes - only measurable with a PDF text layer or a known page scale."""
        roles = {"net_quantity": "Net quantity", "product_name": "Product name"}
        for el in self.reading.elements:
            if el.role not in roles:
                continue
            lines = self._lines_for(el)
            sized = [l for l in lines if l.cap_height_mm]
            if not sized:
                self.add(f"Text size: {roles[el.role]}", "info", "", "not measurable",
                         f"Physical size of '{el.text}' cannot be measured (raster image without scale) - "
                         "check by hand.")
                continue
            digit_lines = [l for l in sized if re.search(r"\d", l.text)] or sized
            cap = max(l.cap_height_mm for l in digit_lines)
            src = "PDF text layer" if digit_lines[0].source == "pdf" else "OCR estimate"
            self.add(f"Text size: {roles[el.role]}", "info", "", f"{cap:.2f} mm",
                     f"Measured numeral/cap height ≈ {cap:.2f} mm ({src}; font size "
                     f"{max(l.font_size_mm or 0 for l in digit_lines):.2f} mm em).", quote=el.text)
        pdf_lines = [l for l in self.index.lines if l.font_size_mm]
        if pdf_lines:
            small = min(pdf_lines, key=lambda l: l.font_size_mm)
            self.add("Text size: smallest text", "info", "", f"{small.font_size_mm * X_HEIGHT_RATIO:.2f} mm x-height",
                     f"Smallest text is '{small.text[:40]}' - font size {small.font_size_mm:.2f} mm, "
                     f"x-height ≈ {small.font_size_mm * X_HEIGHT_RATIO:.2f} mm (PDF text layer).")

    def _lines_for(self, el) -> list[TextLine]:
        lines = [self.index.by_id[i] for i in el.line_ids if i in self.index.by_id]
        if not lines:
            m = self.index.locate(el.text)
            lines = m.lines if m and m.verified else []
        return lines


def run_checks(spec, reading, index) -> list[DeterministicCheck]:
    return Checker(spec, reading, index).run()
