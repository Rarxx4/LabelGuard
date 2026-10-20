"""Trust layer: turns raw AI assessments into findings a reviewer can rely on.

The AI proposes a verdict; this module checks it against independent
evidence and downgrades it to NEEDS_REVIEW when it cannot be backed up.
Every adjustment is recorded in `trust_notes`, so the reviewer sees *why*.

Checks applied to each assessment:
  1. Evidence grounding  - quoted artwork text must exist in the text layer / OCR.
  2. Absence re-check    - "X is missing" claims are re-searched on the artwork.
  3. Code agreement      - the verdict must agree with deterministic checks.
  4. Confidence gate     - low-confidence PASS/FAIL become NEEDS_REVIEW.
  5. Source grounding    - spec and rule quotes must exist in their documents.
Deterministic mismatches the AI did not cover become findings of their own.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from . import config
from .grounding import TextIndex, normalize, numbers
from .schemas import (Assessment, DeterministicCheck, Finding, LocatedEvidence, Rule, RuleAssessment,
                      Verdict)

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
VERDICT_ORDER = {Verdict.FAIL: 0, Verdict.NEEDS_REVIEW: 1, Verdict.PASS: 2, Verdict.NOT_APPLICABLE: 3}


def text_contains(document: str, quote: str) -> bool:
    q, d = normalize(quote), normalize(document)
    if len(q) < 3:
        return False
    if q in d:
        return True
    return fuzz.partial_ratio(q, d) >= config.QUOTE_VERIFIED_SCORE and set(numbers(quote)) <= set(numbers(document))


def build_findings(rules: list[Rule], assessment: Assessment, checks: list[DeterministicCheck],
                   index: TextIndex, spec_text: str, rule_texts: dict[str, str]) -> list[Finding]:
    by_rule = {a.rule_id: a for a in assessment.assessments}
    check_map = {c.check_id: c for c in checks}
    all_rule_text = "\n".join(rule_texts.values())
    findings: list[Finding] = []
    covered_checks: set[str] = set()

    for rule in rules:
        a = by_rule.get(rule.rule_id)
        if a is None:
            findings.append(Finding(
                finding_id=f"F{len(findings) + 1}", rule_id=rule.rule_id, title=rule.title,
                check_type=rule.check_type, severity=rule.severity, ai_verdict=Verdict.NEEDS_REVIEW,
                verdict=Verdict.NEEDS_REVIEW, confidence=0.0, summary="The AI did not return an assessment for "
                "this rule.", rule_source=_rule_source(rule), rule_quote=rule.source_quote,
                trust_notes=["No AI assessment - check this rule by hand."]))
            continue
        related = [check_map[c] for c in a.related_check_ids if c in check_map]
        covered_checks.update(c.check_id for c in related)
        findings.append(_assess_one(f"F{len(findings) + 1}", rule, a, related, index, spec_text, all_rule_text))

    # Deterministic problems the AI did not connect to any rule.
    for c in checks:
        if c.check_id in covered_checks or c.status not in ("mismatch", "not_found"):
            continue
        verdict = Verdict.FAIL if c.status == "mismatch" and c.artwork_verified else Verdict.NEEDS_REVIEW
        ev = []
        if c.artwork_quote:
            ev.append(_locate_artwork(c.artwork_quote, [], index, "Printed on artwork"))
        findings.append(Finding(
            finding_id=f"F{len(findings) + 1}", rule_id="SPEC", title=f"Artwork vs approved spec: {c.topic}",
            check_type="match_approved_info", severity="major", ai_verdict=verdict, verdict=verdict,
            confidence=1.0 if verdict == Verdict.FAIL else 0.5,
            summary=f"{c.topic}: approved '{c.expected}', artwork '{c.found or 'not found'}'. {c.detail}",
            expected=c.expected, found=c.found, evidence=ev, related_checks=[c.check_id], origin="deterministic",
            rule_source="Approved product specification",
            trust_notes=[f"Raised by deterministic check {c.check_id} (code, not AI)."]))

    findings.sort(key=lambda f: (VERDICT_ORDER[f.verdict], SEVERITY_ORDER.get(f.severity, 3), f.rule_id))
    for n, f in enumerate(findings, 1):
        f.finding_id = f"F{n}"
    return findings


def _rule_source(rule: Rule) -> str:
    return " - ".join(x for x in (rule.source_document, rule.source_section) if x)


def _locate_artwork(quote: str, line_ids: list[str], index: TextIndex, note: str) -> LocatedEvidence:
    ev = LocatedEvidence(source="artwork", quote=quote, note=note)
    m = index.locate(quote) if quote else None
    if m:
        ev.verified, ev.match_score = m.verified, round(m.score, 1)
        if m.verified:  # never point at a location we could not confirm
            ev.matched_text, ev.page, ev.bbox = m.text, m.page, m.bbox
        elif m.score >= 60:
            ev.matched_text = m.text  # closest text, shown to the reviewer as "did you mean"
    if line_ids and (not m or not m.verified):
        page, bbox = index.bbox_for(line_ids)
        if bbox:
            ev.page, ev.bbox = page, bbox
    return ev


def _assess_one(fid: str, rule: Rule, a: RuleAssessment, related: list[DeterministicCheck], index: TextIndex,
                spec_text: str, rule_text: str) -> Finding:
    notes: list[str] = []
    verdict = a.verdict
    change_reason = ""

    def downgrade(reason: str):
        nonlocal verdict, change_reason
        if verdict in (Verdict.PASS, Verdict.FAIL):
            notes.append(f"AI said {verdict.value} -> NEEDS_REVIEW: {reason}")
            verdict = Verdict.NEEDS_REVIEW
            change_reason = change_reason or reason
        else:
            notes.append(reason)

    # Locate / verify every piece of evidence.
    evidence: list[LocatedEvidence] = []
    for e in a.evidence:
        if e.source == "artwork":
            evidence.append(_locate_artwork(e.quote, e.line_ids, index, e.note))
        else:
            doc = spec_text if e.source == "approved_spec" else rule_text
            evidence.append(LocatedEvidence(source=e.source, quote=e.quote, note=e.note,
                                            verified=bool(e.quote) and text_contains(doc, e.quote)))
    art_ev = [e for e in evidence if e.source == "artwork" and e.quote]
    verified_art = [e for e in art_ev if e.verified]
    unverified = [e for e in art_ev if not e.verified]
    code_mismatch = [c for c in related if c.status in ("mismatch", "not_found") and c.artwork_verified]
    code_match = [c for c in related if c.status == "match"]
    # Locations found by code checks are evidence too (e.g. the exact nutrition row that differs).
    for c in code_mismatch:
        if c.artwork_quote and not any(normalize(c.artwork_quote) == normalize(e.quote) for e in evidence):
            evidence.append(_locate_artwork(c.artwork_quote, [], index, f"Code check {c.check_id}: {c.topic} - "
                                            f"expected '{c.expected}', found '{c.found}'"))

    # 1. Evidence grounding.
    if unverified:
        notes.append("Quoted text not found on artwork: " + "; ".join(f"'{e.quote[:60]}'" for e in unverified))
    if verdict in (Verdict.PASS, Verdict.FAIL) and not a.is_absence_claim and rule.check_type != "visual":
        if art_ev and not verified_art and not (verdict == Verdict.FAIL and code_mismatch):
            downgrade("none of the artwork text the AI cited could be found in the text layer/OCR "
                      "(possible misread).")

    # 2. Absence re-check: is the "missing" thing actually there?
    if verdict == Verdict.FAIL and a.is_absence_claim and rule.search_terms:
        hit = index.find_any(rule.search_terms)
        if hit:
            downgrade(f"possible false alarm - '{hit.text[:60]}' was found on the artwork "
                      f"({', '.join(l.line_id for l in hit.lines)}).")
        else:
            notes.append(f"Absence confirmed: none of {rule.search_terms} found on the artwork.")

    # 3. Agreement with deterministic checks.
    if verdict == Verdict.PASS and code_mismatch:
        details = ", ".join(f"{c.check_id} ({c.topic}: expected '{c.expected}', found '{c.found}')"
                            for c in code_mismatch)
        missing = [c for c in code_mismatch if c.status == "not_found"]
        if rule.check_type == "match_approved_info":
            # Comparing printed values with the spec is arithmetic - the code wins.
            reason = f"deterministic check {details} shows the printed value differs from the approved spec."
            notes.append(f"AI said PASS -> FAIL: {reason}")
            verdict = Verdict.FAIL
            change_reason = reason
        elif missing:
            # Presence / format rule, but code could not find the item at all.
            downgrade("deterministic check " + ", ".join(f"{c.check_id} ({c.topic})" for c in missing)
                      + " did not find this on the artwork.")
        else:
            # A wrong *value* does not contradict a presence/format rule; the value rule reports it.
            notes.append(f"Related value check {details} - reported under the value-matching rule; does not "
                         f"affect this {rule.check_type} rule.")
    if (verdict == Verdict.FAIL and rule.check_type == "match_approved_info" and code_match
            and not code_mismatch):
        downgrade("deterministic checks " + ", ".join(c.check_id for c in code_match)
                  + " found the printed values match the approved spec.")
    if verdict == Verdict.FAIL and code_mismatch:
        notes.append("Confirmed by deterministic check(s) " + ", ".join(c.check_id for c in code_mismatch) + ".")

    # Sizes cannot be judged from a raster image without a known scale.
    if rule.check_type == "numeric_threshold" and any(c.found == "not measurable" for c in related):
        downgrade("physical size cannot be measured from a raster image without scale - measure on the "
                  "print-ready PDF or a proof.")

    # 4. Confidence gate.
    if verdict in (Verdict.PASS, Verdict.FAIL) and a.confidence < config.MIN_CONFIDENCE_FOR_VERDICT:
        downgrade(f"AI confidence {a.confidence:.2f} is below {config.MIN_CONFIDENCE_FOR_VERDICT}.")
    if verdict == Verdict.FAIL and rule.check_type == "visual" and a.confidence < config.MIN_CONFIDENCE_FOR_VISUAL_FAIL:
        downgrade(f"visual judgement with confidence {a.confidence:.2f} - a human should confirm.")

    # 5. Source grounding for spec / rule quotes (informational).
    for e in evidence:
        if e.source != "artwork" and e.quote and not e.verified:
            notes.append(f"{e.source.replace('_', ' ').title()} quote not found in the source document: "
                         f"'{e.quote[:60]}'")
    rule_ok = text_contains(rule_text, rule.source_quote)
    if not rule_ok:
        notes.append("The rule's source quote could not be matched verbatim in the rulebook - check the rule "
                     "wording.")

    summary, reasoning = a.summary, a.reasoning
    if change_reason:  # the AI's own summary no longer describes the verdict
        summary = change_reason[0].upper() + change_reason[1:]
        extra = "" if a.reasoning.strip() == a.summary.strip() else " " + a.reasoning
        reasoning = f"{a.verdict.value} - {a.summary}{extra}".strip()

    return Finding(
        finding_id=fid, rule_id=rule.rule_id, title=rule.title, check_type=rule.check_type,
        severity=rule.severity, ai_verdict=a.verdict, verdict=verdict, confidence=a.confidence,
        summary=summary, expected=a.expected, found=a.found, reasoning=reasoning,
        suggested_fix=a.suggested_fix, evidence=evidence, rule_source=_rule_source(rule),
        rule_quote=rule.source_quote, rule_quote_verified=rule_ok, trust_notes=notes,
        related_checks=[c.check_id for c in related])


def readiness(findings: list[Finding]) -> dict:
    """Overall launch decision, honouring reviewer decisions (dismissed findings are ignored)."""
    active = [f for f in findings if f.review_decision != "dismissed"]
    # A NEEDS_REVIEW finding the reviewer confirmed counts as a failure.
    fails = [f for f in active if f.verdict == Verdict.FAIL
             or (f.verdict == Verdict.NEEDS_REVIEW and f.review_decision == "confirmed")]
    review = [f for f in active if f.verdict == Verdict.NEEDS_REVIEW and f.review_decision is None]
    passes = [f for f in active if f.verdict == Verdict.PASS]
    if fails:
        status, label = "not_ready", "NOT READY TO PRINT"
    elif review:
        status, label = "review", "NEEDS HUMAN REVIEW"
    else:
        status, label = "ready", "READY TO PRINT"
    return {"status": status, "label": label, "fail": len(fails), "review": len(review), "pass": len(passes),
            "na": sum(f.verdict == Verdict.NOT_APPLICABLE for f in active),
            "critical": sum(f.severity == "critical" for f in fails),
            "dismissed": len(findings) - len(active),
            "adjusted": sum(f.verdict != f.ai_verdict for f in findings if f.origin == "ai")}
