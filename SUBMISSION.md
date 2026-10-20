# Esko AIForge — submission: LabelGuard

**Theme 2:** Is this Packaging Artwork ready to launch?

---

## 1. The problem and our approach

**Problem.** Before packaging artwork goes to print, someone must check every required declaration. They confirm that the text matches the approved product information, that numbers and claims are correct, and that the artwork follows the market's regulations (e.g. FSSAI, FDA) and the company's own interpretation of them. This is done by hand today: reading PDFs side by side with spec sheets and rulebooks. It is slow, and mistakes are costly. A wrong net quantity, a missing allergen declaration or a prohibited claim can mean a reprint or a recall.

AI can read artwork, but on its own it is not trustworthy enough for this job. It can misread a number, invent a quote, or claim something is missing when it is there. A checker that raises false alarms gets ignored, and one that misses errors is dangerous.

**Our approach: LabelGuard.** A reviewer uploads the artwork, the rules and the approved spec. LabelGuard returns a launch-readiness verdict and a rule-by-rule list of findings: **PASS**, **FAIL**, or **NEEDS REVIEW**. Each finding includes the evidence highlighted on the artwork, the exact rule text it comes from, and a suggested fix.

Responsibility is split three ways:

1. **AI (Google Gemini 3.8 Flash by default, or Claude Opus 5.5; vision + reasoning)** does what code cannot. It turns a free-text rulebook into testable rules, extracts approved facts from a spec, understands the artwork (what is a claim, which panel is the front, is the veg symbol present), and judges each rule.
2. **Deterministic code** does what AI should not. It extracts the exact text and positions from the PDF (or OCR for images), measures text height in millimetres, and compares values arithmetically: net quantity with unit conversion, ingredient order and QUID percentages, nutrition values, licence digits, and approved claims.
3. **A trust layer** checks every AI claim against independent evidence before the reviewer sees it:
   - Quotes must be found on the artwork, and numbers must match exactly.
   - "Something is missing" claims are re-searched.
   - When the AI disagrees with arithmetic on a value-matching rule, the code wins.
   - Low-confidence and unmeasurable judgements go to a human.

   Anything it cannot verify becomes **NEEDS REVIEW**, with the reason shown. On the demo artwork, it corrects three planted AI mistakes: a hallucinated "Best Before is missing", an invented MRP quote, and a missed sodium mismatch.

The reviewer stays in control. They can confirm or dismiss each finding as a false alarm, ask follow-up questions in a chat grounded in the run, and export an HTML report for the design agency.

## 2. Architecture / flow

See `docs/architecture.png`.

```
Artwork (PDF/PNG/JPG) ─┐
Rules (PDF/DOCX/TXT) ──┼─► Ingest (PyMuPDF text layer + positions + sizes │ RapidOCR for images)
Approved spec (XLSX…) ─┘                         │
            ┌────────────────────────────────────┼─────────────────────────────┐
            ▼                                    ▼                             ▼
   [AI] rulebook → rules             [AI] spec → approved facts     [AI vision] read artwork
            └────────────────────────────────────┼─────────────────────────────┘
                                                 ▼
                       [Code] deterministic checks (spec vs artwork, mm measurements)
                                                 ▼
                       [AI vision] rule-by-rule assessment with evidence + confidence
                                                 ▼
          [Trust layer] grounding · absence re-check · code agreement · confidence gates
                                                 ▼
     Reviewer UI: verdict · evidence on artwork · confirm/dismiss · chat · HTML/JSON report
```

## 3. AI models and technologies

- **Google Gemini 3.8 Flash** (`google-genai` SDK, free tier) is the default model. **Claude Opus 5.5** (Anthropic SDK) is a drop-in alternative. Either model is used for four structured steps (rules, spec facts, artwork reading, assessment) and a follow-up chat. Every step uses **structured outputs**: responses must match a JSON schema generated from Pydantic, and are validated again on receipt. Thinking level is set per step (high for artwork reading and assessment), images are sent at high resolution for small label text, and responses are cached on disk.
- **PyMuPDF**: page rendering and the PDF text layer, with exact coordinates and font sizes.
- **RapidOCR** (PaddleOCR models on ONNX Runtime): an independent second reader for raster artwork and outlined text.
- **RapidFuzz**: evidence grounding with number-strict normalisation.
- **Streamlit** for the UI; python-docx / openpyxl / pandas for document input.
- 27 automated tests run fully offline, using a fake LLM that makes deliberate mistakes.

## 4. Demo

A 3–5 minute recording uses the sample files: `samples/artwork_v1_masala_peanuts.pdf` (7 planted errors), its PNG version, and the corrected v2.

## 5. Code

GitHub repository: <add link>
