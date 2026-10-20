"""Follow-up questions about a run ("Why is F3 a failure?", "What should the designer change?")."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from . import config, prompts
from .llm import image_block, text_block
from .schemas import RunResult


def _run_context(run: RunResult) -> str:
    findings = [f.model_dump(mode="json", exclude={"evidence"}) | {
        "evidence": [{"source": e.source, "quote": e.quote, "verified": e.verified} for e in f.evidence]}
        for f in run.findings]
    return (
        f"<findings>{json.dumps(findings, ensure_ascii=False)}</findings>\n"
        f"<rules>{json.dumps([r.model_dump() for r in run.rules], ensure_ascii=False)}</rules>\n"
        f"<approved_spec>{run.spec_facts.model_dump_json() if run.spec_facts else 'none'}</approved_spec>\n"
        f"<artwork_reading>{run.reading.model_dump_json()}</artwork_reading>\n"
        f"<deterministic_checks>{json.dumps([c.model_dump() for c in run.checks], ensure_ascii=False)}"
        f"</deterministic_checks>"
    )


def ask(llm, run: RunResult, history: list[dict], question: str, focus_finding: str | None = None) -> Iterator[str]:
    """history: [{'role': 'user'|'assistant', 'content': str}, ...] (previous turns, text only)."""
    first = [image_block(Path(p.png_path).read_bytes()) for p in run.pages]
    first.append(text_block("Run data:\n" + _run_context(run)))
    messages = [{"role": "user", "content": first},
                {"role": "assistant", "content": "I have the run data and the artwork. What would you like to know?"}]
    messages += history
    q = question if not focus_finding else f"(About finding {focus_finding}) {question}"
    messages.append({"role": "user", "content": q})
    chat = getattr(llm, "chat", None) or llm.stream_text  # .chat() adds caching
    return chat(prompts.CHAT, messages, config.EFFORT["chat"])
