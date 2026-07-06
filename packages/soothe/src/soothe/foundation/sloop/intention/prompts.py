"""LLM prompts for intake classification (RFC-630, IG-540, IG-554).

Static classification rules live in system fragments. The human message is
built in Python (``GOAL:`` plain text, same shape as plan-assess).

Two-pass prompts (IG-554):
- ``INTAKE_PASS1_SYSTEM_PROMPT``: Social vs task classification (no prior context).
- ``INTAKE_PASS2_SYSTEM_PROMPT``: Scope classification (trivial/simple/complex).
"""

from __future__ import annotations

from pathlib import Path

_CLASSIFIER_FRAGMENTS_DIR = (
    Path(__file__).resolve().parent.parent / "prompts" / "fragments" / "classifiers"
)


def _read_classifier_fragment(name: str) -> str:
    return (_CLASSIFIER_FRAGMENTS_DIR / name).read_text(encoding="utf-8")


INTAKE_CLASSIFICATION_SYSTEM_PROMPT = _read_classifier_fragment("intake_classification_system.xml")
INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT = _read_classifier_fragment(
    "intake_classification_retry_system.xml"
)

# Two-pass prompts (IG-554)
INTAKE_PASS1_SYSTEM_PROMPT = _read_classifier_fragment("intake_pass1_system.xml")
INTAKE_PASS2_SYSTEM_PROMPT = _read_classifier_fragment("intake_pass2_system.xml")

INTAKE_CLASSIFICATION_HUMAN_TASK = "Classify GOAL above. JSON only."

INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY = "Re-classify GOAL above. JSON only."

# Pass 1/2 human tasks (IG-554)
INTAKE_PASS1_HUMAN_TASK = "Classify above. JSON only."
INTAKE_PASS2_HUMAN_TASK = "Classify CURRENT_GOAL scope. JSON only."

__all__ = [
    "INTAKE_CLASSIFICATION_HUMAN_TASK",
    "INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY",
    "INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT",
    "INTAKE_CLASSIFICATION_SYSTEM_PROMPT",
    "INTAKE_PASS1_HUMAN_TASK",
    "INTAKE_PASS1_SYSTEM_PROMPT",
    "INTAKE_PASS2_HUMAN_TASK",
    "INTAKE_PASS2_SYSTEM_PROMPT",
]
