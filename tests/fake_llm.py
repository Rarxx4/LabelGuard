"""Canned LLM responses for the bundled v1 sample - lets the whole pipeline (and the UI) run without an
API key. The answers deliberately contain three typical AI mistakes so tests can prove the trust layer
catches them:
  * LBL-10: claims "Best Before" is missing (it is printed)            -> absence re-check
  * LBL-09: quotes text that is not on the artwork ("MRP ₹ 60/-")       -> evidence grounding
  * LBL-05: says PASS although sodium differs from the spec            -> code agreement
"""
from __future__ import annotations

from labelguard.schemas import (ArtworkElement, ArtworkReading, Assessment, Evidence, LabelFacts, NutritionRow,
                                OtherFact, Rule, RuleAssessment, RuleSet, SymbolObservation, Verdict)

RB = "rulebook_snacks_india.pdf"
NUTRITION = [("Energy", "560", "kcal"), ("Protein", "18.5", "g"), ("Carbohydrate", "30.2", "g"),
             ("Total Sugars", "2.1", "g"), ("Added Sugars", "0", "g"), ("Total Fat", "40.5", "g"),
             ("Saturated Fat", "7.8", "g"), ("Trans Fat", "0.1", "g"), ("Sodium", "560", "mg")]
ING = ("Peanuts (72%), Gram Flour (Besan), Edible Vegetable Oil (Palmolein), Spices & Condiments (Red Chilli, "
       "Turmeric, Coriander, Cumin), Iodised Salt, Curry Leaves (1%), Black Salt, Acidity Regulator (INS 330)")


def _rule(rid, title, req, ctype, sev, quote, terms=(), section="Section A - Mandatory declarations"):
    return Rule(rule_id=rid, title=title, requirement=req, check_type=ctype, severity=sev, applies_when="always",
                source_document=RB, source_section=section, source_quote=quote, search_terms=list(terms))


RULES = RuleSet(rules=[
    _rule("LBL-01", "Name of the food", "Product name on front panel matches approved name", "match_approved_info",
          "major", "The name of the food must appear on the front panel (principal display panel) and must match "
          "the approved product name exactly."),
    _rule("LBL-02a", "Net quantity declared and correct", "Net quantity on front panel matches approved quantity",
          "match_approved_info", "critical", "The net quantity must be declared on the front panel in metric units "
          "(g or kg) and must match the approved net quantity."),
    _rule("LBL-02b", "Net quantity numeral height", "Net quantity numerals at least 4 mm high", "numeric_threshold",
          "major", "The numerals of the net quantity declaration must be at least 4 mm high."),
    _rule("LBL-03", "Ingredients list", "Ingredients match approved formulation incl. QUID", "match_approved_info",
          "major", "The list must match the approved formulation, including the declared percentage of "
          "characterising ingredients (QUID).", ["Ingredients"]),
    _rule("LBL-04", "Allergen declaration", "A 'Contains:' statement lists all allergens", "presence", "critical",
          "Allergens present in the product must be declared in a separate \"Contains:\" statement immediately "
          "after the ingredient list (for example \"Contains: Peanuts\").", ["Contains:", "Contains Peanuts"]),
    _rule("LBL-05", "Nutrition information", "Nutrition per 100 g matches approved data", "match_approved_info",
          "major", "All values must match the approved nutrition data."),
    _rule("LBL-06", "Veg symbol", "Green veg symbol on front panel", "visual", "major",
          "Vegetarian products must carry the green vegetarian symbol (a green square outline containing a filled "
          "green circle) on the front panel, close to the name of the food."),
    _rule("LBL-07", "FSSAI licence", "14-digit licence matching spec", "format", "critical",
          "The FSSAI logo and the 14-digit FSSAI licence number of the brand owner must be displayed."),
    _rule("LBL-09", "MRP", "MRP with 'Incl. of all taxes'", "format", "major",
          "The MRP must be declared as \"MRP Rs.\" (or the Rupee symbol) followed by the amount and the words "
          "\"Incl. of all taxes\".", ["MRP", "Incl. of all taxes"]),
    _rule("LBL-10", "Date marking", "Best Before statement present", "presence", "major",
          "The pack must declare a \"Best Before\" or \"Use By\" statement", ["Best Before", "Use By"]),
    _rule("CLM-02", "Protein claim threshold", "High protein needs >= 20 g/100 g", "claim", "critical",
          "\"High protein\" requires at least 20 g protein per 100 g.", section="Section B - Claims"),
    _rule("CLM-03", "Prohibited health claims", "No immunity / disease claims", "claim", "critical",
          "Claims that a food prevents, treats or cures a disease, or boosts immunity, are prohibited on snack "
          "products.", section="Section B - Claims"),
])

SPEC = LabelFacts(
    product_name="Masala Crunch Peanuts", brand="Crunchwell", net_quantity="200 g", ingredients=ING,
    allergens_contains=["Peanuts"], allergens_may_contain=["Gluten"], nutrition_basis="per 100 g",
    nutrition=[NutritionRow(nutrient=n, value=v, unit=u) for n, v, u in NUTRITION],
    licence_numbers=["10012345000678"], mrp="Rs. 60.00 (Incl. of all taxes)", claims=["Source of Protein"],
    veg_status="Vegetarian", storage="Store in a cool, dry place. Once opened, transfer contents to an airtight "
    "container.", date_marking="Best Before 6 months from manufacture",
    manufacturer="Crunchwell Foods Pvt. Ltd., Plot 42, MIDC Industrial Area, Chakan, Pune, Maharashtra - 410501, "
    "India", customer_care="1800-123-4567 | care@crunchwell.in", other=[OtherFact(name="Target market",
                                                                               value="India")])


def _el(i, role, text, panel):
    return ArtworkElement(element_id=f"E{i}", role=role, text=text, page=0, panel=panel, line_ids=[])


ART_ING = ING.replace("Peanuts (72%)", "Peanuts (70%)")
READING = ArtworkReading(
    panels=["front", "back"],
    elements=[
        _el(1, "brand", "CRUNCHWELL", "front"), _el(2, "product_name", "Masala Crunch Peanuts", "front"),
        _el(3, "descriptor", "Roasted & Spiced Peanut Snack", "front"), _el(4, "claim", "HIGH PROTEIN", "front"),
        _el(5, "claim", "Boosts Immunity!", "front"), _el(6, "net_quantity", "Net Wt. 150 g", "front"),
        _el(7, "ingredients", ART_ING + ".", "back"),
        _el(8, "allergen_statement", "May contain traces of gluten.", "back"),
        _el(9, "nutrition_table", "NUTRITIONAL INFORMATION (Approx.) Per 100 g", "back"),
        _el(10, "licence", "Lic. No. 1001234500067", "back"),
        _el(11, "mrp", "MRP Rs. 60.00 (Incl. of all taxes)", "back"),
    ],
    symbols=[SymbolObservation(name="vegetarian symbol", present=True, description="Green square with filled green "
                               "circle, top right of front panel", page=0, panel="front"),
             SymbolObservation(name="FSSAI logo", present=True, description="'fssai' wordmark in blue box", page=0,
                               panel="back")],
    facts=LabelFacts(
        product_name="Masala Crunch Peanuts", brand="CRUNCHWELL", net_quantity="Net Wt. 150 g",
        ingredients=ART_ING, allergens_contains=[], allergens_may_contain=["gluten"],
        allergen_statement="May contain traces of gluten.", nutrition_basis="Per 100 g",
        nutrition=[NutritionRow(nutrient=n, value="610" if n == "Sodium" else v, unit=u) for n, v, u in NUTRITION],
        licence_numbers=["Lic. No. 1001234500067"], mrp="MRP Rs. 60.00 (Incl. of all taxes)",
        claims=["HIGH PROTEIN", "Boosts Immunity!"], veg_status="Vegetarian symbol present",
        storage="Store in a cool, dry place. Once opened, transfer contents to an airtight container.",
        date_marking="Best Before 6 months from manufacture.",
        manufacturer="Crunchwell Foods Pvt. Ltd., Plot 42, MIDC Industrial Area, Chakan, Pune, Maharashtra - "
                     "410501, India",
        customer_care="1800-123-4567 | care@crunchwell.in"),
    legibility_concerns=["Net quantity text on the front panel is small relative to the panel."])


def _a(rid, verdict, conf, summary, exp, found, ev, absence=False, checks=(), fix=""):
    return RuleAssessment(rule_id=rid, verdict=verdict, confidence=conf, summary=summary, expected=exp, found=found,
                          is_absence_claim=absence, evidence=ev, reasoning=summary, suggested_fix=fix or "None",
                          related_check_ids=list(checks))


def _art(q, note=""):
    return Evidence(source="artwork", quote=q, line_ids=[], note=note)


ASSESSMENT = Assessment(assessments=[
    _a("LBL-01", Verdict.PASS, 0.95, "Product name matches.", "Masala Crunch Peanuts", "Masala Crunch Peanuts",
       [_art("Masala Crunch")], checks=["D1"]),
    _a("LBL-02a", Verdict.FAIL, 0.97, "Net quantity printed as 150 g but approved quantity is 200 g.", "200 g",
       "150 g", [_art("Net Wt. 150 g"), Evidence(source="approved_spec", quote="200 g", line_ids=[], note="")],
       checks=["D3"], fix="Change to 'Net Wt. 200 g'."),
    _a("LBL-02b", Verdict.FAIL, 0.9, "Net quantity numerals are about 2.3 mm high, below the 4 mm minimum.",
       ">= 4 mm", "≈2.3 mm", [_art("Net Wt. 150 g")], checks=["D25"], fix="Increase to at least 18 pt."),
    _a("LBL-03", Verdict.FAIL, 0.93, "Peanut percentage is 70% on artwork vs 72% approved.", "Peanuts (72%)",
       "Peanuts (70%)", [_art("Peanuts (70%)")], checks=["D4"], fix="Change to Peanuts (72%)."),
    _a("LBL-04", Verdict.FAIL, 0.95, "No 'Contains:' allergen statement; only a 'May contain' line.",
       "Contains: Peanuts", "May contain traces of gluten.", [_art("May contain traces of gluten.")], absence=True,
       checks=["D5"], fix="Add 'Contains: Peanuts.' after the ingredients."),
    # Mistake: misses the sodium mismatch.
    _a("LBL-05", Verdict.PASS, 0.85, "Nutrition table present per 100 g with all nutrients.", "Approved values",
       "All present", [_art("NUTRITIONAL INFORMATION (Approx.)")], checks=["D15"]),
    _a("LBL-06", Verdict.PASS, 0.9, "Green veg symbol on front panel.", "Veg symbol", "Present",
       [Evidence(source="artwork", quote="", line_ids=[], note="Green square with dot, top right")]),
    _a("LBL-07", Verdict.FAIL, 0.96, "Licence number has 13 digits and does not match the approved number.",
       "10012345000678", "1001234500067", [_art("Lic. No. 1001234500067")], checks=["D16"]),
    # Mistake: quotes text that is not printed.
    _a("LBL-09", Verdict.PASS, 0.9, "MRP declared correctly.", "MRP Rs. xx (Incl. of all taxes)", "MRP ₹ 60/-",
       [_art("MRP ₹ 60/- inclusive of taxes")]),
    # Mistake: hallucinated absence.
    _a("LBL-10", Verdict.FAIL, 0.8, "No Best Before statement found.", "Best Before statement", "Not found", [],
       absence=True),
    _a("CLM-02", Verdict.FAIL, 0.95, "'HIGH PROTEIN' claimed with 18.5 g protein; 20 g required.", ">= 20 g",
       "18.5 g", [_art("HIGH PROTEIN"), _art("Protein (g) 18.5")], checks=["D22"]),
    _a("CLM-03", Verdict.FAIL, 0.97, "'Boosts Immunity!' is a prohibited health claim.", "No immunity claims",
       "Boosts Immunity!", [_art("Boosts Immunity!")], checks=["D23"], fix="Remove the claim."),
])


class FakeLLM:
    model = "fake-llm (offline test fixtures)"

    def structured(self, name, system, content, schema, effort="medium", max_tokens=0):
        return {"rules": RULES, "spec": SPEC, "artwork": READING, "assess": ASSESSMENT}[name]

    def stream_text(self, system, messages, effort="medium"):
        yield "Offline test mode: chat answers need a Claude API key."
