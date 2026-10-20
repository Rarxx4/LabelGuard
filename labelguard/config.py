"""Central settings. Everything can be overridden through environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# AI provider: "gemini" (default, free tier available) or "claude".
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
PROVIDER = os.getenv("LABELGUARD_PROVIDER") or (
    "claude" if os.getenv("ANTHROPIC_API_KEY") and not GEMINI_API_KEY else "gemini")
GEMINI_MODEL = os.getenv("LABELGUARD_GEMINI_MODEL", "gemini-3.8-flash")
CLAUDE_MODEL = os.getenv("LABELGUARD_CLAUDE_MODEL") or os.getenv("LABELGUARD_MODEL", "claude-opus-5-5")

# Effort per pipeline step: reading the artwork and judging rules are the
# accuracy-critical steps, extracting facts from a spec sheet is routine.
EFFORT = {
    "rules": os.getenv("LABELGUARD_EFFORT_RULES", "medium"),
    "spec": os.getenv("LABELGUARD_EFFORT_SPEC", "low"),
    "artwork": os.getenv("LABELGUARD_EFFORT_ARTWORK", "high"),
    "assess": os.getenv("LABELGUARD_EFFORT_ASSESS", "high"),
    "chat": os.getenv("LABELGUARD_EFFORT_CHAT", "medium"),
}

DATA_DIR = Path(os.getenv("LABELGUARD_DATA_DIR", ROOT / "data"))
RUNS_DIR = DATA_DIR / "runs"
CACHE_DIR = DATA_DIR / "cache"
SAMPLES_DIR = ROOT / "samples"

# Rendering: long edge of page images sent to the model / shown in the UI.
RENDER_LONG_EDGE_PX = int(os.getenv("LABELGUARD_RENDER_PX", "2400"))
# A PDF page with less text than this is treated as outlined artwork -> OCR.
MIN_TEXT_LAYER_CHARS = 40

# Trust layer thresholds.
QUOTE_VERIFIED_SCORE = 90      # fuzzy score (0-100) for "this text is on the artwork"
MIN_CONFIDENCE_FOR_VERDICT = 0.6
MIN_CONFIDENCE_FOR_VISUAL_FAIL = 0.8

USE_CACHE = os.getenv("LABELGUARD_CACHE", "1") != "0"
