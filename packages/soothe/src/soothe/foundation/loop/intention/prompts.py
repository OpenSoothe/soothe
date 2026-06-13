"""LLM prompts for intent classification (RFC-225).

Two-value classification with piggybacked quiz answer: the LLM decides whether
a query is a simple quiz (greeting, thanks, static trivia answerable without
tools) or requires the agentic loop. When quiz, the LLM also provides the
direct answer (``quiz_response``) to avoid a second LLM call. Loop continuation
is derived structurally inside ``StrangeLoop`` from the checkpoint, not classified.

Prompt bodies live as ``.xml`` fragments under
``soothe.core.prompts.fragments.classifiers``; this module loads them directly
to avoid importing ``soothe.core.prompts`` (circular import with config).

XML structure:
- <intent_instructions>: Static content (classification rules, JSON schema)
- <intent_inputs> (retry only): Dynamic runtime fields as flat XML elements
  - <current_time>, <current_query>: Runtime context
"""

from __future__ import annotations

from pathlib import Path

_CLASSIFIER_FRAGMENTS_DIR = (
    Path(__file__).resolve().parent.parent / "prompts" / "fragments" / "classifiers"
)


def _read_classifier_fragment(name: str) -> str:
    return (_CLASSIFIER_FRAGMENTS_DIR / name).read_text(encoding="utf-8")


# Intent classification prompt (quiz detection only; continue/new_goal decided structurally)
INTENT_CLASSIFICATION_PROMPT = _read_classifier_fragment("intent_classification.xml")

# Retry prompt (simplified)
INTENT_CLASSIFICATION_RETRY_PROMPT = _read_classifier_fragment("intent_classification_retry.xml")

__all__ = [
    "INTENT_CLASSIFICATION_PROMPT",
    "INTENT_CLASSIFICATION_RETRY_PROMPT",
]
