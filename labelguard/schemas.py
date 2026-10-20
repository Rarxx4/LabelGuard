"""Data models.

Two groups:
  * LLM output schemas - Claude is forced to answer in exactly these shapes
    (structured outputs), so every response is machine-checkable.
  * Internal models - what the pipeline produces after ingestion,
    deterministic checks and trust verification.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Shared enums
# --------------------------------------------------------------------------
class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


Severity = Literal["critical", "major", "minor"]
CheckType = Literal[
    "presence",            # something must be printed
    "match_approved_info", # printed value must equal the approved spec
    "format",              # pattern / wording requirement
    "numeric_threshold",   # measurable limit (size, amount)
    "claim",               # claim substantiation / prohibited claims
    "visual",              # symbol, placement, layout
    "other",
]


# --------------------------------------------------------------------------
# LLM output: rules extracted from a rulebook / regulation
# --------------------------------------------------------------------------
class Rule(BaseModel):
    rule_id: str = Field(description="ID used in the document (e.g. LBL-02) or a generated one like R-07")
    title: str
    requirement: str = Field(description="The requirement restated as one testable sentence")
    check_type: CheckType
    severity: Severity
    applies_when: str = Field(description="Condition for the rule to apply, or 'always'")
    source_document: str
    source_section: str = Field(description="Section / heading the rule came from, '' if none")
    source_quote: str = Field(description="Exact sentence(s) copied verbatim from the document")
    search_terms: list[str] = Field(
        description="Short phrases that must appear on the artwork if the rule is satisfied "
        "(e.g. ['Contains:', 'Best Before']). Empty if not applicable."
    )


class RuleSet(BaseModel):
    rules: list[Rule]


# --------------------------------------------------------------------------
# LLM output: label facts (used for both the approved spec and the artwork)
# --------------------------------------------------------------------------
class NutritionRow(BaseModel):
    nutrient: str
    value: str
    unit: str


class OtherFact(BaseModel):
    name: str
    value: str


class LabelFacts(BaseModel):
    """Every field is required in the JSON schema; "" / [] means "not stated" (keeps the schema simple)."""
    model_config = ConfigDict(json_schema_extra=lambda s, _: s.__setitem__("required", list(s["properties"])))

    product_name: str = ""
    brand: str = ""
    net_quantity: str = ""
    ingredients: str = Field("", description="Full ingredient list, verbatim")
    allergens_contains: list[str] = Field(default_factory=list)
    allergens_may_contain: list[str] = Field(default_factory=list)
    allergen_statement: str = Field("", description="Allergen sentence(s) verbatim")
    nutrition_basis: str = Field("", description="e.g. 'per 100 g'")
    nutrition: list[NutritionRow] = Field(default_factory=list)
    licence_numbers: list[str] = Field(default_factory=list)
    mrp: str = ""
    claims: list[str] = Field(default_factory=list, description="Marketing / nutrition / health claims")
    veg_status: str = ""
    storage: str = ""
    date_marking: str = ""
    manufacturer: str = ""
    customer_care: str = ""
    other: list[OtherFact] = Field(default_factory=list)


# --------------------------------------------------------------------------
# LLM output: what the AI sees on the artwork
# --------------------------------------------------------------------------
ElementRole = Literal[
    "brand", "product_name", "descriptor", "net_quantity", "ingredients",
    "allergen_statement", "nutrition_table", "claim", "licence", "mrp",
    "date_marking", "storage", "manufacturer", "customer_care", "symbol",
    "barcode", "other",
]


class ArtworkElement(BaseModel):
    element_id: str = Field(description="E1, E2, ...")
    role: ElementRole
    text: str = Field(description="Text exactly as printed; for symbols a short description")
    page: int = Field(description="0-based page index")
    panel: str = Field(description="e.g. 'front', 'back', 'side'")
    line_ids: list[str] = Field(description="IDs of the provided text lines (L..) this element covers; [] if none")


class SymbolObservation(BaseModel):
    name: str = Field(description="e.g. 'vegetarian symbol', 'FSSAI logo', 'recycling mark'")
    present: bool
    description: str = Field(description="What it looks like and where it is")
    page: int
    panel: str


class ArtworkReading(BaseModel):
    panels: list[str]
    elements: list[ArtworkElement]
    symbols: list[SymbolObservation]
    facts: LabelFacts
    legibility_concerns: list[str]


# --------------------------------------------------------------------------
# LLM output: rule-by-rule evaluation
# --------------------------------------------------------------------------
class Evidence(BaseModel):
    source: Literal["artwork", "approved_spec", "rule"]
    quote: str = Field(description="Verbatim text from that source (empty only for visual evidence)")
    line_ids: list[str] = Field(description="Artwork line IDs (L..) backing the quote; [] if none")
    note: str = Field(description="What this evidence shows")


class RuleAssessment(BaseModel):
    rule_id: str
    verdict: Verdict
    confidence: float = Field(description="0.0-1.0, how sure you are about the verdict")
    summary: str = Field(description="One sentence a packaging reviewer can act on")
    expected: str
    found: str
    is_absence_claim: bool = Field(description="True if the verdict rests on something NOT being on the artwork")
    evidence: list[Evidence]
    reasoning: str = Field(description="Why this matters and how the verdict was reached, 1-3 sentences")
    suggested_fix: str
    related_check_ids: list[str] = Field(description="IDs of deterministic checks (D..) that relate to this rule")


class Assessment(BaseModel):
    assessments: list[RuleAssessment]


# --------------------------------------------------------------------------
# Internal models
# --------------------------------------------------------------------------
class TextLine(BaseModel):
    line_id: str
    page: int
    text: str
    bbox: tuple[float, float, float, float]  # normalised x0, y0, x1, y1 (top-left origin)
    source: Literal["pdf", "ocr"]
    font_size_mm: Optional[float] = None
    cap_height_mm: Optional[float] = None
    confidence: float = 1.0


class PageImage(BaseModel):
    index: int
    png_path: str
    width_px: int
    height_px: int
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None


class DeterministicCheck(BaseModel):
    check_id: str
    topic: str
    status: Literal["match", "mismatch", "not_found", "info"]
    expected: str = ""
    found: str = ""
    detail: str = ""
    artwork_quote: str = ""
    artwork_verified: bool = True  # was the AI's transcription found in the text layer / OCR?


class LocatedEvidence(BaseModel):
    source: str
    quote: str
    note: str = ""
    verified: bool = False
    match_score: float = 0.0
    matched_text: str = ""
    page: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None


class Finding(BaseModel):
    finding_id: str
    rule_id: str
    title: str
    check_type: str
    severity: str
    ai_verdict: Verdict
    verdict: Verdict
    confidence: float
    summary: str
    expected: str = ""
    found: str = ""
    reasoning: str = ""
    suggested_fix: str = ""
    evidence: list[LocatedEvidence] = Field(default_factory=list)
    rule_source: str = ""
    rule_quote: str = ""
    rule_quote_verified: bool = True
    trust_notes: list[str] = Field(default_factory=list)
    related_checks: list[str] = Field(default_factory=list)
    origin: Literal["ai", "deterministic"] = "ai"
    review_decision: Optional[Literal["confirmed", "dismissed"]] = None
    review_note: str = ""


class RunResult(BaseModel):
    run_id: str
    created_at: str
    market: str
    model: str
    artwork_name: str
    rulebook_names: list[str]
    spec_name: Optional[str]
    pages: list[PageImage]
    lines: list[TextLine]
    rules: list[Rule]
    spec_facts: Optional[LabelFacts]
    reading: ArtworkReading
    checks: list[DeterministicCheck]
    findings: list[Finding]
    documents: dict[str, str] = Field(default_factory=dict)  # source text of rulebooks / spec, by file name
    timings: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
