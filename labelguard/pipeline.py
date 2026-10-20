"""End-to-end pre-flight check.

    files ─► ingest ─┬─► [AI] rules from rulebook(s) ──────┐
                     ├─► [AI] approved facts from spec ────┤
                     └─► [AI] read artwork (vision) ───────┤
                                                           ▼
                          deterministic checks (code) ─► [AI] rule-by-rule assessment
                                                           ▼
                                trust layer ─► findings + launch readiness

The three AI reads are independent and run in parallel.
"""
from __future__ import annotations

import io
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image

from . import config, prompts
from .deterministic import run_checks
from .grounding import TextIndex
from .ingest import document_to_text, ingest_artwork
from .llm import image_block, text_block
from .schemas import ArtworkReading, Assessment, LabelFacts, PageImage, RuleSet, RunResult, TextLine
from .trust import build_findings, text_contains

Progress = Callable[[str], None]
MAX_IMAGE_BYTES = 4_500_000


def page_image_blocks(pages: list[PageImage]) -> list[dict]:
    blocks = []
    for p in pages:
        data = Path(p.png_path).read_bytes()
        if len(data) > MAX_IMAGE_BYTES:  # API image size limit
            buf = io.BytesIO()
            Image.open(io.BytesIO(data)).convert("RGB").save(buf, "JPEG", quality=88)
            blocks += [text_block(f"Artwork page {p.index}:"), image_block(buf.getvalue(), "image/jpeg")]
        else:
            blocks += [text_block(f"Artwork page {p.index}:"), image_block(data)]
    return blocks


def lines_table(lines: list[TextLine]) -> str:
    rows = ["id | page | x,y (0-1, top-left) | size | source | text"]
    for l in lines:
        size = f"{l.cap_height_mm:.2f}mm cap" if l.cap_height_mm else "-"
        rows.append(f"{l.line_id} | {l.page} | {l.bbox[0]:.3f},{l.bbox[1]:.3f} | {size} | {l.source} | {l.text}")
    return "\n".join(rows)


def dump(model) -> str:
    return json.dumps(model.model_dump(mode="json") if hasattr(model, "model_dump") else model,
                      ensure_ascii=False, separators=(",", ":"))


def run_pipeline(artwork: tuple[str, bytes], rulebooks: list[tuple[str, bytes]], spec: tuple[str, bytes] | None,
                 market: str, llm, progress: Progress = lambda m: None) -> RunResult:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    run_dir = config.RUNS_DIR / run_id
    timings: dict[str, float] = {}

    def timed(name, fn, *args):
        t = time.time()
        out = fn(*args)
        timings[name] = round(time.time() - t, 1)
        return out

    # 1. Ingest -------------------------------------------------------------
    progress("Reading files: rendering artwork, extracting text layer / OCR")
    pages, lines, warnings = timed("ingest", ingest_artwork, artwork[1], artwork[0], run_dir)
    rule_texts = {name: document_to_text(data, name) for name, data in rulebooks}
    spec_text = document_to_text(spec[1], spec[0]) if spec else ""
    index = TextIndex(lines)
    progress(f"Artwork: {len(pages)} page(s), {len(lines)} text lines "
             f"({'PDF text layer' if lines and lines[0].source == 'pdf' else 'OCR'})")
    images = page_image_blocks(pages)

    # 2. Three independent AI reads, in parallel --------------------------
    def extract_rules():
        docs = "\n\n".join(f"<document name=\"{n}\">\n{t}\n</document>" for n, t in rule_texts.items())
        return llm.structured("rules", prompts.RULES, [text_block(
            f"Target market: {market}\n\nExtract the checklist from these documents:\n\n{docs}")],
            RuleSet, config.EFFORT["rules"])

    def extract_spec():
        if not spec:
            return None
        return llm.structured("spec", prompts.SPEC, [text_block(
            f"<document name=\"{spec[0]}\">\n{spec_text}\n</document>")], LabelFacts, config.EFFORT["spec"])

    def read_artwork():
        return llm.structured("artwork", prompts.ARTWORK, images + [text_block(
            "Detected text lines:\n" + lines_table(lines))], ArtworkReading, config.EFFORT["artwork"])

    progress("AI: extracting rules, approved facts and reading the artwork (in parallel)")
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_rules = pool.submit(timed, "ai_rules", extract_rules)
        f_spec = pool.submit(timed, "ai_spec", extract_spec)
        f_art = pool.submit(timed, "ai_artwork", read_artwork)
        ruleset, facts, reading = f_rules.result(), f_spec.result(), f_art.result()
    progress(f"Rules: {len(ruleset.rules)} checkable rules | Artwork: {len(reading.elements)} elements, "
             f"{len(reading.symbols)} symbols")
    unverified_rules = [r.rule_id for r in ruleset.rules if not text_contains("\n".join(rule_texts.values()),
                                                                              r.source_quote)]
    if unverified_rules:
        warnings.append(f"Source quote of rule(s) {', '.join(unverified_rules)} not found verbatim in the rulebook.")

    # 3. Deterministic checks ----------------------------------------------
    progress("Code: comparing artwork with approved spec, measuring text sizes")
    checks = timed("checks", run_checks, facts, reading, index)
    n_mis = sum(c.status in ("mismatch", "not_found") for c in checks)
    progress(f"Deterministic checks: {len(checks)} run, {n_mis} mismatch(es)")

    # 4. Rule-by-rule assessment -------------------------------------------
    progress(f"AI: assessing {len(ruleset.rules)} rules against the artwork")
    context = (
        f"Target market: {market}\n\n"
        f"<rules>{dump(ruleset)}</rules>\n\n"
        f"<approved_spec>{dump(facts) if facts else 'No approved spec was provided.'}</approved_spec>\n\n"
        f"<artwork_reading>{dump(reading)}</artwork_reading>\n\n"
        f"<deterministic_checks>{json.dumps([c.model_dump() for c in checks], ensure_ascii=False)}"
        f"</deterministic_checks>\n\n"
        f"<detected_text_lines>\n{lines_table(lines)}\n</detected_text_lines>\n\n"
        "Assess every rule."
    )
    assessment = timed("ai_assess", llm.structured, "assess", prompts.ASSESS, images + [text_block(context)],
                       Assessment, config.EFFORT["assess"])

    # 5. Trust layer ------------------------------------------------------
    progress("Trust layer: verifying evidence, re-checking 'missing' claims, cross-checking with code")
    findings = build_findings(ruleset.rules, assessment, checks, index, spec_text, rule_texts)

    result = RunResult(
        run_id=run_id, created_at=datetime.now().isoformat(timespec="seconds"), market=market,
        model=getattr(llm, "model", "unknown"), artwork_name=artwork[0], rulebook_names=list(rule_texts),
        spec_name=spec[0] if spec else None, pages=pages, lines=lines, rules=ruleset.rules, spec_facts=facts,
        reading=reading, checks=checks, findings=findings,
        documents={**rule_texts, **({spec[0]: spec_text} if spec else {})}, timings=timings, warnings=warnings)
    save_run(result)
    progress("Done")
    return result


def save_run(result: RunResult):
    run_dir = config.RUNS_DIR / result.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")


RECORDED_DIR = config.SAMPLES_DIR / "recorded_runs"  # real AI runs shipped with the repo


def _run_dir(run_id: str) -> Path:
    own = config.RUNS_DIR / run_id
    return own if (own / "result.json").exists() else RECORDED_DIR / run_id


def load_run(run_id: str) -> RunResult:
    run_dir = _run_dir(run_id)
    result = RunResult.model_validate_json((run_dir / "result.json").read_text(encoding="utf-8"))
    for p in result.pages:  # page images saved on another machine / folder: look next to result.json
        if not Path(p.png_path).exists():
            p.png_path = str(run_dir / re.split(r"[\\/]", p.png_path)[-1])
    return result


def list_runs() -> list[dict]:
    out, seen = [], set()
    for base, recorded in ((config.RUNS_DIR, False), (RECORDED_DIR, True)):
        if not base.exists():
            continue
        for d in sorted(base.iterdir(), reverse=True):
            f = d / "result.json"
            if f.exists() and d.name not in seen:
                seen.add(d.name)
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append({"run_id": data["run_id"], "created": data["created_at"],
                            "artwork": data["artwork_name"] + (" (recorded example)" if recorded else "")})
    return out
