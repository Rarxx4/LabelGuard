# How LabelGuard works: a guide for presenting it

This guide is for whoever presents LabelGuard. It follows one run through the code and lists the questions judges are likely to ask.

## The idea in one sentence
**AI reads and reasons, code measures and compares, and a trust layer decides which AI claims can be believed.**

## One run, step by step (`labelguard/pipeline.py`, function `run_pipeline`)

1. **Ingest** (`ingest.py`)
   - PDF artwork: PyMuPDF renders each page to a PNG (for the AI and the screen). It also reads the PDF's text layer: every line of text with its exact box and font size. Font size in points × 25.4/72 = mm, so text height can be *measured*.
   - Image artwork, or a PDF where the text was converted to shapes ("outlines", common in print files): RapidOCR reads the lines instead (`ocr.py`).
   - Each line gets an ID (L1, L2, ...). These IDs let the AI point at exact text.
   - Rulebooks and specs (PDF/DOCX/XLSX) are converted to plain text.

2. **Three AI calls in parallel** (`ThreadPoolExecutor`)
   - `rules`: rulebook text → a list of `Rule` objects (id, requirement, type, severity, *verbatim* source quote, search terms).
   - `spec`: spec text → `LabelFacts` (net quantity, ingredients, allergens, nutrition, ...).
   - `artwork`: page images + the detected text lines → `ArtworkReading` (elements with roles and line IDs, symbols, and the facts *as printed*).
   - **Structured outputs** (`llm.py`): we turn a Pydantic class into a JSON schema, the API makes the model answer in that shape, and we validate it again with Pydantic (with one automatic retry if it doesn't fit). Think of it as a model with a fixed output head instead of free text.
   - **Provider-agnostic**: `GeminiClient` and `ClaudeClient` implement the same two methods (`structured`, `stream_text`). The pipeline doesn't know which model it is talking to; the fake LLM used in the tests is just a third implementation.

3. **Deterministic checks** (`deterministic.py`), plain Python with no AI
   - Compares artwork facts with spec facts: `200 g` vs `0.2 kg` (unit conversion), ingredient lists (split on commas outside brackets, compare order and %), nutrition numbers, licence digits, claims against the approved claims list.
   - Measures text sizes from the PDF text layer.
   - Each check records whether the AI's transcription was actually found on the artwork.

4. **Assessment**: one more AI call. It gets the rules, facts, reading, code-check results and images, and returns one `RuleAssessment` per rule: verdict, confidence, evidence quotes with line IDs, reasoning and fix.

5. **Trust layer** (`trust.py`, function `_assess_one`). For each assessment:
   - **Grounding**: each quoted piece of artwork text is searched for in the text layer / OCR (`grounding.py`). If none is found → NEEDS_REVIEW.
   - **Absence re-check**: if the AI says "X is missing", we search for the rule's search terms. If found → possible false alarm → NEEDS_REVIEW.
   - **Code agreement**: AI says PASS, code says the values differ → FAIL (for value-matching rules) or NEEDS_REVIEW (otherwise).
   - **Confidence gates**: confidence < 0.6 → NEEDS_REVIEW. Visual FAIL with confidence < 0.8 → NEEDS_REVIEW.
   - **Unmeasurable sizes**: a size rule on a raster image → NEEDS_REVIEW.
   - Every change is written to `trust_notes`, which the UI shows.

6. **UI** (`app.py`, Streamlit): verdict banner, metrics, artwork with evidence boxes (`viz.py`), finding cards, reviewer decisions, chat (`chat.py`) and the HTML report (`report.py`).

## The matcher (`grounding.py`), in brief
- `normalize()` lower-cases, removes spaces and punctuation, and treats `l`, `I` and `|` the same. OCR often drops spaces ("Maycontaintraces") and confuses l/I.
- `locate(quote)` tries windows of 1–6 neighbouring lines (the line below, or the next cell to the right for tables). It scores each window with RapidFuzz `partial_ratio` and keeps the best.
- **Numbers must match exactly**. That's why "Net Wt. 200 g" is never "verified" against "Net Wt. 150 g", even though the strings are 80 % similar.
- `locate_row(label, value)` handles tables: find the row label, then check the value in the same row.

## Likely judge questions

**Why not just ask the AI "is this artwork compliant?"**
It would give an answer you can't verify. We split the problem so every AI claim is checkable. Quotes must exist, numbers are compared by code, and absences are re-searched. When we can't verify a claim, we say so instead of guessing.

**How do you avoid false alarms?**
Three ways: (1) the absence re-check (the "Best Before" example), (2) the prompt tells the AI not to fail on capitalisation or punctuation, (3) reviewers can dismiss a finding, and it then no longer affects the verdict.

**How do you handle uncertainty?**
The NEEDS_REVIEW state, with a reason. Sources of uncertainty: low confidence, unverifiable evidence, AI/code disagreement, and things that can't be measured from the input (physical size on a photo).

**Which model, and why?**
The default is Gemini 3.8 Flash: free tier, strong vision on dense small text, long context and structured JSON output. Claude Opus 5.5 can be switched in with one setting for higher accuracy. The trust layer is model-independent. A weaker or cheaper model simply produces more NEEDS_REVIEW findings instead of wrong answers, which is exactly why the layer exists.

**Why not run a model locally (Ollama)?**
We tried sizing it. On a laptop without a dedicated GPU, a small local vision model would take tens of minutes per check and read 7-pt label text much less reliably. The provider interface makes adding one easy later.

**What if the PDF has no text layer?**
Pages with almost no text fall back to OCR automatically. Sizes are then estimated from OCR box height and the page scale, and the source of each measurement is shown in the UI.

**Does it only work on your sample?**
No. Nothing is hard-coded to the sample: rules come from whatever rulebook is uploaded, and facts from whatever spec. The offline demo mode is the only sample-specific part, and it exists only so the app can be shown without an API key.

**What does it cost / how fast is it?**
Four AI calls per artwork (three in parallel) plus optional chat. That fits within Gemini's free-tier limits, and results are cached, so re-checking the same files costs nothing.

**What would you build next?**
Panel/dieline detection for placement rules, multilingual packs, turning reviewer dismissals into rulebook clarifications, and integration with an approval workflow such as Esko WebCenter.

## Running the tests
`pytest -q` runs 27 tests offline. `tests/fake_llm.py` makes three deliberate mistakes (hallucinated absence, invented quote, missed sodium mismatch), and the tests check that the trust layer catches each one.
