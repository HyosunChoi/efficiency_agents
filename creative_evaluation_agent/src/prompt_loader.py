"""Loads the benchmark prompt text — shared by benchmark_runner.py (actual API calls) and
cost_estimator.py (needs the same fixed text to estimate its token count before any call).
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def load_benchmark_prompt_text() -> str:
    taxonomy = (PROMPTS_DIR / "creative_analysis_prompt.md").read_text(encoding="utf-8")
    wrapper = (PROMPTS_DIR / "benchmark_prompt.md").read_text(encoding="utf-8")
    return f"{wrapper}\n\n---\n\n{taxonomy}"
