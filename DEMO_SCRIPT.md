# Demo video script (target 4 minutes)

**Before recording**

- Put your free Gemini key in `.env` (`GEMINI_API_KEY=...`), then run `streamlit run app.py`.
- If you hit a free-tier rate limit (HTTP 429), wait a minute and press Run again. Finished steps are cached.
- Run each sample once beforehand: v1 PDF, v1 PNG, v2 PDF. The AI responses are cached, so during the recording each run finishes in seconds.
- Browser at 100–110 % zoom, full screen. Close other tabs.

---

**0:00 – 0:25 · The problem**
> "Before packaging goes to print, someone has to check every word against regulations, the company rulebook and the approved product data. That's slow, and one mistake means a reprint or a recall. AI can help, but only if you can trust it. That's what LabelGuard is built around."

**0:25 – 0:50 · Inputs**
- Show the input screen and switch on the sample files.
- Briefly open the three files: the artwork PDF (front and back panel), the rulebook PDF and the spec XLSX.
> "Three inputs: the artwork, the rules (FSSAI-based company rulebook), and the approved product spec. Market: India."

**0:50 – 1:20 · Run**
- Click **Run pre-flight check** and let the progress steps show.
> "The AI reads the rulebook into testable rules, extracts the approved facts and reads the artwork, all in parallel. Code then compares values and measures text sizes. The AI assesses each rule. Finally a trust layer verifies what the AI said."

**1:20 – 2:30 · Results**
- Banner: **NOT READY TO PRINT**, with the counts.
- Walk through 3–4 failures, clicking **📍 Show** on each:
  - Net quantity 150 g vs 200 g: expected vs found, and the source rule quote.
  - Allergen: there's no "Contains: Peanuts", only a "May contain" line. Point out that the trust layer confirmed the absence by searching again.
  - Numeral height: measured 2.3 mm from the PDF, the rule needs 4 mm.
  - "Boosts Immunity!": a prohibited health claim.

**2:30 – 3:20 · Trust layer (the key part)**
- Open the **AI verdicts corrected** metric, then point to the orange NEEDS REVIEW cards:
  - "Here the AI said the Best Before date was missing. LabelGuard searched the artwork, found it, and flagged a possible false alarm instead of a false FAIL."
  - "Here the AI quoted text that isn't on the pack, so we don't trust that PASS."
  - Nutrition card: "The AI thought nutrition was fine. Code compared the values: sodium is 610 vs 560 approved. For value matching, code wins, and it highlights the exact row."
- Dismiss one finding as a false alarm and show the counts update.

**3:20 – 3:45 · Ask + report**
- Ask on a finding: *"What exactly should the designer change?"*
- Open the **Export** tab and the HTML report.

**3:45 – 4:10 · Robustness**
- New check with the PNG version: "Same findings via OCR. A size rule can't be measured from a photo, so it goes to a human."
- New check with v2 (fixed): the verdict changes.
> "LabelGuard: AI where it adds value, code where it must be exact, and a human for whatever can't be verified."

**Tip:** if Esko's own sample files arrived by mail, show one of them for 20–30 seconds as well. It proves the tool isn't tuned to our own sample.
