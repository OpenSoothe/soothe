"""LLM prompts for 4-class intake classification (RFC-630, IG-540).

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

INTAKE_CLASSIFICATION_HUMAN_TASK = (
    "Classify GOAL above. Reply with JSON only. "
    "When intake_label is not quiz: set reasoning to one first-person sentence "
    "(I'll or Let me, max 20 words) stating your next concrete action — paraphrase GOAL, "
    "never mention intake labels, complexity, routing, or classification rationale."
)

INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY = (
    "Re-classify GOAL above. Reply with JSON only. "
    "reasoning must start with I'll or Let me and describe your next action only — "
    "never echo label jargon (forbidden: single focused step, trivial, simple, complex)."
)

# Back-compat aliases (system-only; human envelope is code-built).
INTAKE_CLASSIFICATION_PROMPT = INTAKE_CLASSIFICATION_SYSTEM_PROMPT
INTAKE_CLASSIFICATION_RETRY_PROMPT = INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT
INTAKE_CLASSIFICATION_HUMAN_PROMPT = "GOAL:\n{query}\n\nTASK:\n" + INTAKE_CLASSIFICATION_HUMAN_TASK
INTAKE_CLASSIFICATION_RETRY_HUMAN_PROMPT = (
    "GOAL:\n{query}\n\nTASK:\n" + INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY
)

__all__ = [
    "INTAKE_CLASSIFICATION_HUMAN_PROMPT",
    "INTAKE_CLASSIFICATION_HUMAN_TASK",
    "INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY",
    "INTAKE_CLASSIFICATION_PROMPT",
    "INTAKE_CLASSIFICATION_RETRY_HUMAN_PROMPT",
    "INTAKE_CLASSIFICATION_RETRY_PROMPT",
    "INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT",
    "INTAKE_CLASSIFICATION_SYSTEM_PROMPT",
]
