"""LLM prompts for two-pass intake classification (RFC-630, IG-554).

- ``INTAKE_PASS1_SYSTEM_PROMPT``: Social vs task (no prior context).
- ``INTAKE_PASS2_SYSTEM_PROMPT``: Scope (trivial/simple/complex).
"""

from __future__ import annotations

from pathlib import Path

_CLASSIFIER_FRAGMENTS_DIR = (
    Path(__file__).resolve().parent.parent / "prompts" / "fragments" / "classifiers"
)


def _read_classifier_fragment(name: str) -> str:
    return (_CLASSIFIER_FRAGMENTS_DIR / name).read_text(encoding="utf-8")


INTAKE_PASS1_SYSTEM_PROMPT = _read_classifier_fragment("intake_pass1_system.xml")
INTAKE_PASS2_SYSTEM_PROMPT = _read_classifier_fragment("intake_pass2_system.xml")

INTAKE_PASS1_HUMAN_TASK = "Classify above. JSON only."
INTAKE_PASS2_HUMAN_TASK = "Classify CURRENT_GOAL scope. JSON only."

__all__ = [
    "INTAKE_PASS1_HUMAN_TASK",
    "INTAKE_PASS1_SYSTEM_PROMPT",
    "INTAKE_PASS2_HUMAN_TASK",
    "INTAKE_PASS2_SYSTEM_PROMPT",
]
