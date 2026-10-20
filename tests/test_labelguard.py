"""Tests run fully offline (fake LLM with deliberately wrong answers) - `pytest -q`."""
from pathlib import Path

import pytest

from labelguard import config
from labelguard.deterministic import parse_quantity, split_ingredients
from labelguard.grounding import TextIndex
from labelguard.ingest import document_to_text, ingest_artwork
from labelguard.pipeline import run_pipeline
from labelguard.schemas import Verdict
from labelguard.trust import readiness
from tests.fake_llm import FakeLLM

S = config.SAMPLES_DIR


def _read(name):
    return name, (S / name).read_bytes()


@pytest.fixture(scope="module", params=["artwork_v1_masala_peanuts.pdf", "artwork_v1_masala_peanuts.png"])
def run(request, tmp_path_factory):
    config.RUNS_DIR = tmp_path_factory.mktemp("runs")
    return run_pipeline(_read(request.param), [_read("rulebook_snacks_india.pdf")],
                        _read("approved_product_spec.xlsx"), "India (FSSAI)", FakeLLM())


def by_rule(run, rule_id):
    return next(f for f in run.findings if f.rule_id == rule_id)


# ---------------------------------------------------------------- grounding
@pytest.fixture(scope="module")
def index(tmp_path_factory):
    _, lines, _ = ingest_artwork(*reversed(_read("artwork_v1_masala_peanuts.pdf")), tmp_path_factory.mktemp("a"))
    return TextIndex(lines)


def test_quote_found_on_artwork(index):
    assert index.locate("Net Wt. 150 g").verified


def test_wrong_number_never_verifies(index):
    m = index.locate("Net Wt. 200 g")
    assert not m.verified and not m.numbers_ok


def test_multi_line_quote(index):
    m = index.locate("Peanuts (70%), Gram Flour (Besan), Edible Vegetable Oil (Palmolein), Spices & Condiments "
                     "(Red Chilli, Turmeric, Coriander, Cumin), Iodised Salt, Curry Leaves (1%), Black Salt")
    assert m.verified and len(m.lines) == 2


def test_table_row_lookup(index):
    assert index.locate_row("Sodium", "610").verified
    assert not index.locate_row("Sodium", "560").verified
    assert index.locate_row("Protein", "18.5").verified  # not fooled by the "HIGH PROTEIN" claim


def test_absent_text_not_found(index):
    assert index.find_any(["Contains:", "Contains Peanuts"]) is None


def test_pdf_text_size_measured(index):
    net = next(l for l in index.lines if "Net Wt" in l.text)
    assert net.cap_height_mm == pytest.approx(2.29, abs=0.05)


# ---------------------------------------------------------------- parsing
def test_quantity_units():
    assert parse_quantity("Net Wt. 0.2 kg") == parse_quantity("200 g") == 200


def test_ingredient_split_respects_brackets():
    items = split_ingredients("Ingredients: Peanuts (72%), Spices (Chilli, Cumin), Salt.")
    assert items == ["Peanuts (72%)", "Spices (Chilli, Cumin)", "Salt"]


def test_documents_to_text():
    assert "10012345000678" in document_to_text(*reversed(_read("approved_product_spec.xlsx")))
    assert "LBL-04" in document_to_text(*reversed(_read("rulebook_snacks_india.pdf")))


# ---------------------------------------------------------------- pipeline + trust layer
def test_all_planted_errors_fail(run):
    for rule_id in ["LBL-02a", "LBL-03", "LBL-04", "LBL-05", "LBL-07", "CLM-02", "CLM-03"]:
        assert by_rule(run, rule_id).verdict == Verdict.FAIL, rule_id
    assert readiness(run.findings)["status"] == "not_ready"


def test_trust_layer_overrides_ai_pass_with_code(run):
    f = by_rule(run, "LBL-05")  # AI said PASS, sodium differs from spec
    assert f.ai_verdict == Verdict.PASS and f.verdict == Verdict.FAIL
    assert any("Sodium" in e.quote and e.verified for e in f.evidence)


def test_trust_layer_catches_hallucinated_absence(run):
    f = by_rule(run, "LBL-10")  # AI said "Best Before" missing - it is printed
    assert f.ai_verdict == Verdict.FAIL and f.verdict == Verdict.NEEDS_REVIEW
    assert any("false alarm" in n for n in f.trust_notes)


def test_trust_layer_catches_invented_quote(run):
    f = by_rule(run, "LBL-09")  # AI quoted text that is not on the artwork
    assert f.ai_verdict == Verdict.PASS and f.verdict == Verdict.NEEDS_REVIEW
    assert not f.evidence[0].verified and f.evidence[0].bbox is None


def test_real_absence_confirmed(run):
    f = by_rule(run, "LBL-04")
    assert any("Absence confirmed" in n for n in f.trust_notes)


def test_size_rule_needs_review_on_raster(run):
    f = by_rule(run, "LBL-02b")
    expected = Verdict.NEEDS_REVIEW if run.lines[0].source == "ocr" else Verdict.FAIL
    assert f.verdict == expected


def test_reviewer_dismissal_changes_readiness(run):
    before = readiness(run.findings)["fail"]
    f = by_rule(run, "CLM-03")
    f.review_decision = "dismissed"
    assert readiness(run.findings)["fail"] == before - 1
    f.review_decision = None


def test_corrected_artwork_has_the_fixes(tmp_path):
    _, lines, _ = ingest_artwork(*reversed(_read("artwork_v2_masala_peanuts_fixed.pdf")), tmp_path)
    idx = TextIndex(lines)
    assert idx.locate("Contains: Peanuts").verified
    assert idx.locate_row("Sodium", "560").verified
    assert next(l for l in lines if "Net Wt" in l.text).cap_height_mm >= 4


# ---------------------------------------------------------------- providers (no network)
def test_gemini_schema_has_no_refs():
    import json
    from labelguard.llm import _inline_refs
    from labelguard.schemas import ArtworkReading, Assessment
    for schema in (ArtworkReading, Assessment):
        assert "$ref" not in json.dumps(_inline_refs(schema.model_json_schema()))


def test_provider_factory():
    from labelguard.llm import ClaudeClient, GeminiClient, LLMError, make_llm
    assert isinstance(make_llm("gemini", api_key="test"), GeminiClient)
    assert isinstance(make_llm("claude", api_key="test"), ClaudeClient)
    with pytest.raises(LLMError):
        make_llm("unknown")


def test_recorded_runs_open_on_any_machine(tmp_path):
    """Recorded real-AI runs ship with the repo and must open without a key or local data."""
    from labelguard import pipeline
    from labelguard.viz import annotate
    config.RUNS_DIR = tmp_path / "runs"
    runs = pipeline.list_runs()
    assert len(runs) >= 3 and all("recorded" in r["artwork"] for r in runs)
    for r in runs:
        run = pipeline.load_run(r["run_id"])
        assert Path(run.pages[0].png_path).exists()
        annotate(run.pages[0], run.findings)
