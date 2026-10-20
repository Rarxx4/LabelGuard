"""LabelGuard - Streamlit UI.

Run:  streamlit run app.py
"""
from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

# Hosted on Streamlit Community Cloud: settings come from the app's Secrets. Copy them into the
# environment before labelguard reads its configuration.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float, bool)):
            os.environ.setdefault(_k, str(_v))
except Exception:  # no secrets file when running locally - .env is used instead
    pass

from labelguard import config  # noqa: E402
from labelguard.chat import ask  # noqa: E402
from labelguard.grounding import TextIndex  # noqa: E402
from labelguard.llm import LLMError, make_llm  # noqa: E402
from labelguard.pipeline import list_runs, load_run, run_pipeline, save_run  # noqa: E402
from labelguard.report import build_html  # noqa: E402
from labelguard.schemas import Verdict  # noqa: E402
from labelguard.trust import readiness  # noqa: E402
from labelguard.viz import annotate  # noqa: E402

# Optional: when set, visitors must enter this code to use the app owner's API key
# (protects a shared link from using up the owner's quota). Visitors can always use their own key.
ACCESS_CODE = os.getenv("APP_ACCESS_CODE", "")

st.set_page_config(page_title="LabelGuard", page_icon="🛡️", layout="wide")

ICON = {Verdict.FAIL: "🔴", Verdict.NEEDS_REVIEW: "🟠", Verdict.PASS: "🟢", Verdict.NOT_APPLICABLE: "⚪"}
LABEL = {Verdict.FAIL: "FAIL", Verdict.NEEDS_REVIEW: "NEEDS REVIEW", Verdict.PASS: "PASS",
         Verdict.NOT_APPLICABLE: "N/A"}
MARKETS = ["India (FSSAI)", "USA (FDA)", "EU (Regulation 1169/2011)", "Other - as defined in the rulebook"]
SAMPLES = {
    "v1 - PDF with planted errors": "artwork_v1_masala_peanuts.pdf",
    "v1 - PNG (raster, uses OCR)": "artwork_v1_masala_peanuts.png",
    "v2 - corrected PDF": "artwork_v2_masala_peanuts_fixed.pdf",
}

st.markdown("""
<style>
.lg-banner{padding:14px 20px;border-radius:10px;color:#fff;font-size:1.35rem;font-weight:700;margin-bottom:6px}
.lg-not_ready{background:#c62828}.lg-review{background:#e08a00}.lg-ready{background:#2e7d32}
.lg-q{border-left:3px solid #999;padding:2px 10px;color:#444;font-style:italic;margin:4px 0}
.block-container{padding-top:1.6rem}
</style>""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("run", None)
ss.setdefault("selected", None)
ss.setdefault("chats", {})
if ss.run is None and (rid := st.query_params.get("run")):  # ?run=<id> opens a saved run
    try:
        ss.run = load_run(rid)
    except FileNotFoundError:
        st.query_params.clear()


# --------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("🛡️ LabelGuard")
    st.caption("AI pre-flight check for packaging artwork")
    providers = {"gemini": "Google Gemini (free tier)", "claude": "Anthropic Claude"}
    provider = st.selectbox("AI provider", list(providers), format_func=providers.get,
                            index=list(providers).index(config.PROVIDER))
    env_key = config.GEMINI_API_KEY if provider == "gemini" else os.getenv("ANTHROPIC_API_KEY", "")
    if env_key and ACCESS_CODE:
        code = st.text_input("Access code", type="password",
                             help="Ask the app owner for the code to use the built-in AI key - or paste your own "
                                  "free key below.")
        server_key_ok = code == ACCESS_CODE
        if code and not server_key_ok:
            st.error("Wrong access code.")
    else:
        server_key_ok = bool(env_key)
    key = st.text_input(f"{'Gemini' if provider == 'gemini' else 'Claude'} API key", type="password", value="",
                        placeholder="built-in key in use" if server_key_ok else (
                            "free key: aistudio.google.com/apikey" if provider == "gemini" else "sk-ant-..."),
                        help="Your own key (optional when the built-in key is available)")
    offline = st.toggle("Offline demo mode", value=not (server_key_ok or key),
                        help="Canned AI responses for the bundled v1 sample, so the app can be explored without "
                             "an API key. Deterministic checks and the trust layer still run for real.")
    model_name = config.GEMINI_MODEL if provider == "gemini" else config.CLAUDE_MODEL
    st.caption(f"Model: `{model_name}`" if not offline else "Model: offline fixtures")
    st.divider()
    runs = list_runs()
    if runs:
        st.subheader("Previous runs")
        choice = st.selectbox("Open a run", ["-"] + [f"{r['run_id']} · {r['artwork']}" for r in runs],
                              label_visibility="collapsed")
        if choice != "-" and st.button("Open", width="stretch"):
            ss.run = load_run(choice.split(" · ")[0])
            ss.selected, ss.chats = None, {}
            st.rerun()


def get_llm():
    if offline:
        from tests.fake_llm import FakeLLM
        return FakeLLM()
    if not key and not server_key_ok:
        raise LLMError("No API key available: enter the access code, paste your own free Gemini key "
                       "(aistudio.google.com/apikey), or switch on Offline demo mode. The recorded examples under "
                       "'Previous runs' work without a key.")
    return make_llm(provider, api_key=key or None)


def safe_ask(run, history, question, finding_id=None):
    try:
        stream = ask(get_llm(), run, list(history), question, finding_id)
        with st.spinner("Thinking... (free-tier AI can take a minute or two)"):
            first = next(stream, "")  # wait for the first part of the answer
        yield first
        yield from stream
    except LLMError as e:
        yield f"_{e}_"


# --------------------------------------------------------------------------- input
def input_view():
    st.title("Is this packaging artwork ready to launch?")
    st.write("Upload the artwork, the rules it must follow and the approved product information. "
             "LabelGuard reads the artwork, checks every rule, shows the evidence, and separates "
             "**definite problems** from **things a human must verify**.")

    use_samples = st.toggle("Use the bundled sample files", value=offline)
    c1, c2, c3 = st.columns(3)
    if use_samples:
        with c1:
            sample = st.selectbox("Artwork", list(SAMPLES), disabled=offline,
                                  help="Offline mode only has fixtures for v1.")
            art_name = SAMPLES["v1 - PDF with planted errors"] if offline else SAMPLES[sample]
            artwork = (art_name, (config.SAMPLES_DIR / art_name).read_bytes())
        with c2:
            st.text_input("Rules", "rulebook_snacks_india.pdf", disabled=True)
            rulebooks = [("rulebook_snacks_india.pdf", (config.SAMPLES_DIR / "rulebook_snacks_india.pdf").read_bytes())]
        with c3:
            st.text_input("Approved product information", "approved_product_spec.xlsx", disabled=True)
            spec = ("approved_product_spec.xlsx", (config.SAMPLES_DIR / "approved_product_spec.xlsx").read_bytes())
    else:
        with c1:
            f_art = st.file_uploader("1 · Artwork", type=["pdf", "png", "jpg", "jpeg", "webp", "tif", "tiff"])
        with c2:
            f_rules = st.file_uploader("2 · Rules (regulation / company rulebook)", accept_multiple_files=True,
                                       type=["pdf", "docx", "txt", "md", "png", "jpg"])
        with c3:
            f_spec = st.file_uploader("3 · Approved product information (optional)",
                                      type=["xlsx", "xls", "csv", "docx", "pdf", "txt", "md", "json"])
        artwork = (f_art.name, f_art.getvalue()) if f_art else None
        rulebooks = [(f.name, f.getvalue()) for f in f_rules or []]
        spec = (f_spec.name, f_spec.getvalue()) if f_spec else None

    market = st.selectbox("Target market", MARKETS)
    ready = artwork and rulebooks
    if st.button("Run pre-flight check", type="primary", disabled=not ready):
        with st.status("Running pre-flight check...", expanded=True) as status:
            if not offline and provider == "gemini":
                st.caption("Gemini free-tier requests can queue for a few minutes. A finished check is cached, so "
                           "running the same files again is instant.")
            try:
                ss.run = run_pipeline(artwork, rulebooks, spec, market, get_llm(), progress=st.write)
                status.update(label="Check complete", state="complete")
            except LLMError as e:
                status.update(label="Check failed", state="error")
                st.error(str(e))
                return
            except Exception as e:  # show the problem instead of a stack trace in the demo
                status.update(label="Check failed", state="error")
                st.exception(e)
                return
        ss.selected, ss.chats = None, {}
        st.rerun()
    if not ready:
        st.caption("Artwork and at least one rules document are required.")


# --------------------------------------------------------------------------- results
def finding_card(run, f):
    with st.expander(f"{ICON[f.verdict]} **{f.finding_id}** · {f.rule_id} · {f.title} — {LABEL[f.verdict]}",
                     expanded=ss.selected == f.finding_id):
        st.markdown(f"**{f.summary}**")
        origin = "deterministic code check" if f.origin == "deterministic" else "AI assessment"
        st.caption(f"Severity: {f.severity} · AI confidence: {f.confidence:.2f} · Source: {origin}")
        if f.verdict != f.ai_verdict:
            st.warning(f"Trust layer changed the AI verdict **{LABEL[f.ai_verdict]} → {LABEL[f.verdict]}**")
        if f.expected or f.found:
            a, b = st.columns(2)
            a.markdown(f"**Expected**  \n{f.expected or '-'}")
            b.markdown(f"**Found on artwork**  \n{f.found or '-'}")
        if f.evidence:
            st.markdown("**Evidence**")
            for e in f.evidence:
                if e.source == "artwork" and not e.quote:
                    st.markdown(f"👁️ *visual* — {e.note}")
                    continue
                mark = "✅" if e.verified else "⚠️"
                where = f" · found at `{e.matched_text[:80]}` ({e.match_score:.0f}/100)" if (
                    e.source == "artwork" and e.matched_text) else ""
                st.markdown(f"{mark} *{e.source.replace('_', ' ')}*: “{e.quote}”{where}")
        if f.reasoning and f.reasoning != f.summary:
            label = "AI's original view" if f.verdict != f.ai_verdict else "Why it matters"
            st.markdown(f"**{label}:** {f.reasoning}")
        if f.suggested_fix and f.suggested_fix != "None":
            st.markdown(f"**Suggested fix:** {f.suggested_fix}")
        if f.rule_quote:
            ok = "✅ verified in source" if f.rule_quote_verified else "⚠️ not found verbatim in source"
            st.markdown(f"**Rule** ({f.rule_source}, {ok})<div class='lg-q'>{f.rule_quote}</div>",
                        unsafe_allow_html=True)
        if f.trust_notes:
            st.markdown("**Trust layer**")
            for n in f.trust_notes:
                st.markdown(f"- {n}")

        c1, c2, c3 = st.columns([1.3, 1.6, 2])
        if c1.button("📍 Show", key=f"show-{f.finding_id}", help="Highlight on the artwork"):
            ss.selected = f.finding_id
            st.rerun()
        options = ["Pending", "Confirm issue", "Dismiss (false alarm)"]
        current = {None: 0, "confirmed": 1, "dismissed": 2}[f.review_decision]
        decision = c2.selectbox("Reviewer decision", options, index=current, key=f"dec-{f.finding_id}",
                                label_visibility="collapsed")
        note = c3.text_input("Note", f.review_note, key=f"note-{f.finding_id}", placeholder="Reviewer note",
                             label_visibility="collapsed")
        new = {0: None, 1: "confirmed", 2: "dismissed"}[options.index(decision)]
        if new != f.review_decision or note != f.review_note:
            f.review_decision, f.review_note = new, note
            save_run(run)
            st.rerun()

        # Inline follow-up questions about this finding.
        history = ss.chats.setdefault(f.finding_id, [])
        for m in history:
            st.chat_message(m["role"]).markdown(m["content"])
        q = st.text_input("Ask about this finding", key=f"ask-{f.finding_id}",
                          placeholder="e.g. Why is this a problem? What exactly should the designer change?")
        if st.button("Ask", key=f"askbtn-{f.finding_id}") and q:
            st.chat_message("user").markdown(q)
            answer = st.chat_message("assistant").write_stream(safe_ask(run, history, q, f.finding_id))
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]


def results_view():
    run = ss.run
    r = readiness(run.findings)
    top1, top2 = st.columns([4, 1])
    with top1:
        st.markdown(f"<div class='lg-banner lg-{r['status']}'>{r['label']}</div>", unsafe_allow_html=True)
        st.caption(f"{run.artwork_name} · rules: {', '.join(run.rulebook_names)} · spec: {run.spec_name or '-'} · "
                   f"{run.market} · run {run.run_id} · {run.model}")
    with top2:
        if st.button("➕ New check", width="stretch"):
            ss.run = None
            st.rerun()
    m = st.columns(5)
    m[0].metric("🔴 Failing", r["fail"], help=f"{r['critical']} critical")
    m[1].metric("🟠 Needs review", r["review"])
    m[2].metric("🟢 Passing", r["pass"])
    m[3].metric("🛡️ AI verdicts corrected", r["adjusted"], help="Changed by the trust layer")
    m[4].metric("⏱️ Total time", f"{sum(run.timings.values()):.0f} s")
    for w in run.warnings:
        st.info(w)

    tabs = st.tabs(["Findings", "Ask LabelGuard", "What the AI read", "Rules", "Code checks", "Export"])

    with tabs[0]:
        left, right = st.columns([1.5, 1])
        with left:
            page_no = 0
            if len(run.pages) > 1:
                page_no = st.radio("Page", range(len(run.pages)), format_func=lambda i: f"Page {i + 1}",
                                   horizontal=True)
            show_pass = st.toggle("Show passing evidence", value=False)
            st.image(annotate(run.pages[page_no], run.findings, ss.selected, show_pass), width="stretch")
            st.caption("🔴 fail · 🟠 needs review · 🟢 pass — boxes show where the evidence was found. "
                       + (f"Highlighting **{ss.selected}**." if ss.selected else "Click 📍 Show on a finding."))
            if ss.selected and st.button("Clear highlight"):
                ss.selected = None
                st.rerun()
        with right:
            flt = st.segmented_control("Filter", ["Fail", "Needs review", "Pass", "N/A"],
                                       selection_mode="multi", default=["Fail", "Needs review"],
                                       label_visibility="collapsed")
            want = {"Fail": Verdict.FAIL, "Needs review": Verdict.NEEDS_REVIEW, "Pass": Verdict.PASS,
                    "N/A": Verdict.NOT_APPLICABLE}
            shown = [f for f in run.findings if f.verdict in {want[x] for x in flt or []}]
            with st.container(height=900):
                if not shown:
                    st.write("Nothing to show for this filter.")
                for f in shown:
                    finding_card(run, f)

    with tabs[1]:
        st.write("Ask anything about this check — e.g. *“Summarise what the designer must change”*, "
                 "*“Which findings need a human and why?”*")
        history = ss.chats.setdefault("_general", [])
        for msg in history:
            st.chat_message(msg["role"]).markdown(msg["content"])
        if q := st.chat_input("Ask LabelGuard"):
            st.chat_message("user").markdown(q)
            answer = st.chat_message("assistant").write_stream(safe_ask(run, history, q))
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]

    with tabs[2]:
        index = TextIndex(run.lines)
        rows = []
        for e in run.reading.elements:
            m_ = index.locate(e.text) if e.role not in ("symbol", "barcode") else None
            rows.append({"id": e.element_id, "role": e.role, "panel": e.panel, "text (as read by AI)": e.text,
                         "confirmed on artwork": "✅" if m_ and m_.verified else ("—" if m_ is None else "⚠️"),
                         "lines": ", ".join(e.line_ids)})
        st.markdown("**Elements the AI identified** — each checked against the "
                    f"{'PDF text layer' if run.lines and run.lines[0].source == 'pdf' else 'OCR text'}")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.markdown("**Symbols**")
        st.dataframe(pd.DataFrame([s.model_dump() for s in run.reading.symbols]), width="stretch",
                     hide_index=True)
        if run.reading.legibility_concerns:
            st.markdown("**Legibility concerns**")
            for c in run.reading.legibility_concerns:
                st.markdown(f"- {c}")
        a, b = st.columns(2)
        with a:
            st.markdown("**Facts printed on the artwork**")
            st.json(run.reading.facts.model_dump(exclude_defaults=True), expanded=False)
        with b:
            st.markdown("**Approved facts from the spec**")
            st.json(run.spec_facts.model_dump(exclude_defaults=True) if run.spec_facts else {}, expanded=False)
        with st.expander("Raw detected text lines (text layer / OCR)"):
            st.dataframe(pd.DataFrame([{"id": l.line_id, "page": l.page, "source": l.source, "text": l.text,
                                        "cap height mm": l.cap_height_mm, "ocr conf": round(l.confidence, 2)}
                                       for l in run.lines]), width="stretch", hide_index=True)

    with tabs[3]:
        st.markdown(f"**{len(run.rules)} checkable rules** extracted from {', '.join(run.rulebook_names)}")
        st.dataframe(pd.DataFrame([{"id": x.rule_id, "title": x.title, "type": x.check_type,
                                    "severity": x.severity, "requirement": x.requirement,
                                    "source quote": x.source_quote} for x in run.rules]),
                     width="stretch", hide_index=True)

    with tabs[4]:
        st.markdown("Deterministic checks run by code (no AI): artwork vs approved spec, and measurements "
                    "from the PDF text layer.")
        st.dataframe(pd.DataFrame([c.model_dump() for c in run.checks]), width="stretch", hide_index=True)

    with tabs[5]:
        st.download_button("⬇️ HTML report (annotated artwork + findings)", build_html(run),
                           file_name=f"labelguard_{run.run_id}.html", mime="text/html")
        st.download_button("⬇️ JSON (full run data)", run.model_dump_json(indent=1),
                           file_name=f"labelguard_{run.run_id}.json", mime="application/json")
        st.caption("Timings (s): " + json.dumps(run.timings))


if ss.run is None:
    input_view()
else:
    results_view()
