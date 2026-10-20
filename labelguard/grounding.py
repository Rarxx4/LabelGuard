"""Grounding: is a piece of text really on the artwork, and where?

The AI's statements are only trusted when the text it quotes can be found in
an independent source - the PDF text layer or OCR. This module answers
"where is this quote?" with a fuzzy match that is strict about numbers
(so "200 g" never verifies against "150 g").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from . import config
from .schemas import TextLine

NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
MAX_WINDOW = 6


def normalize(s: str) -> str:
    """Lower-case, drop spaces/punctuation, fold common OCR confusions (l/I/|)."""
    s = s.lower().replace("|", "i").replace("l", "i")
    return re.sub(r"[^a-z0-9%.]", "", s)


def numbers(s: str) -> list[str]:
    return [n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n
            for n in NUM_RE.findall(s)]


@dataclass
class Match:
    score: float
    numbers_ok: bool
    lines: list[TextLine]

    @property
    def verified(self) -> bool:
        return self.score >= config.QUOTE_VERIFIED_SCORE and self.numbers_ok

    @property
    def text(self) -> str:
        return " ".join(l.text for l in self.lines)

    @property
    def page(self) -> int:
        return self.lines[0].page

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return union_bbox(self.lines)


def union_bbox(lines: list[TextLine]):
    return (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
            max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))


class TextIndex:
    """Positioned lines plus 'reading chains' (a line and the lines directly below it in the same column)."""

    def __init__(self, lines: list[TextLine]):
        self.lines = lines
        self.by_id = {l.line_id: l for l in lines}
        self._norm = {l.line_id: normalize(l.text) for l in lines}
        self._next = {l.line_id: [n for n in (self._line_below(l), self._line_right(l)) if n] for l in lines}

    def _line_right(self, a: TextLine):
        """Next cell on the same row (tables: 'Sodium (mg)' ... '610')."""
        cy = (a.bbox[1] + a.bbox[3]) / 2
        best = None
        for b in self.lines:
            if b.page != a.page or b is a or b.bbox[0] <= a.bbox[2] - 0.002:
                continue
            if not (b.bbox[1] < cy < b.bbox[3]) or b.bbox[0] - a.bbox[2] > 0.25:
                continue
            if best is None or b.bbox[0] < best.bbox[0]:
                best = b
        return best

    def _line_below(self, a: TextLine):
        h = a.bbox[3] - a.bbox[1]
        best, best_gap = None, None
        for b in self.lines:
            if b.page != a.page or b is a or b.bbox[1] <= a.bbox[1]:
                continue
            gap = b.bbox[1] - a.bbox[3]
            if gap > 1.5 * h:
                continue
            overlap = min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0])
            narrower = min(a.bbox[2] - a.bbox[0], b.bbox[2] - b.bbox[0])
            if overlap <= 0.3 * narrower and abs(a.bbox[0] - b.bbox[0]) > 0.01:
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap = b, gap
        return best

    def full_text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    def bbox_for(self, line_ids: list[str]):
        lines = [self.by_id[i] for i in line_ids if i in self.by_id]
        return (lines[0].page, union_bbox(lines)) if lines else (None, None)

    def locate(self, quote: str) -> Match | None:
        q = normalize(quote)
        if len(q) < 2:
            return None
        q_nums = numbers(quote)
        best: Match | None = None
        # Depth-first over windows: each step adds the line below or the cell to the right.
        stack = [[l] for l in self.lines]
        while stack:
            window = stack.pop()
            t = "".join(self._norm[l.line_id] for l in window)
            score = fuzz.partial_ratio(q, t) if t else 0
            if len(t) < 0.8 * len(q):  # window shorter than the quote: penalise
                score *= len(t) / len(q)
            if best is None or score > best.score + 0.5 or (
                    abs(score - best.score) <= 0.5 and len(window) < len(best.lines)):
                w_nums = numbers(" ".join(l.text for l in window))
                best = Match(score=score, numbers_ok=_contains_all(w_nums, q_nums), lines=list(window))
            if len(window) < MAX_WINDOW and len(t) <= 3 * len(q) + 20:
                for nxt in self._next[window[-1].line_id]:
                    if nxt not in window:
                        stack.append(window + [nxt])
        return best

    def locate_row(self, label: str, value: str) -> Match | None:
        """Table lookup: find the row label, then require the value in the same row (or the label's line)."""
        q = normalize(label)
        if len(q) < 2:
            return None
        best = None
        # A label like "Protein" can occur several times ("HIGH PROTEIN" claim, table row) - try each.
        for line in self.lines:
            score = fuzz.partial_ratio(q, self._norm[line.line_id])
            if score < config.QUOTE_VERIFIED_SCORE:
                continue
            row = [line]
            cy = (line.bbox[1] + line.bbox[3]) / 2
            row += [n for n in self._next[line.line_id] if n.bbox[1] < cy < n.bbox[3]]  # cell to the right
            row_text = " ".join(l.text for l in row)
            if numbers(value):
                ok = _contains_all(numbers(row_text), numbers(value))
            else:
                ok = normalize(value) in normalize(row_text)
            m = Match(score=score, numbers_ok=ok, lines=row)
            if ok:
                return m
            best = best or m
        return best

    def find_any(self, terms: list[str]) -> Match | None:
        """Best verified match for any of the terms (used to double-check 'missing' findings)."""
        hits = [m for m in (self.locate(t) for t in terms if t.strip()) if m and m.verified]
        return max(hits, key=lambda m: m.score) if hits else None


def _contains_all(haystack: list[str], needles: list[str]) -> bool:
    pool = list(haystack)
    for n in needles:
        if n in pool:
            pool.remove(n)
        else:
            return False
    return True
