"""LLM prompts for 3-class intake classification (RFC-630, IG-540).

Static classification rules live in system fragments. The human message is
built in Python (``GOAL:`` plain text, same shape as plan-assess).
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

INTAKE_CLASSIFICATION_HUMAN_TASK = "Classify GOAL above. JSON only."

INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY = "Re-classify GOAL above. JSON only."

__all__ = [
    "INTAKE_CLASSIFICATION_HUMAN_TASK",
    "INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY",
    "INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT",
    "INTAKE_CLASSIFICATION_SYSTEM_PROMPT",
]
