"""LLM prompts for 4-class intake classification (RFC-630).

The LLM classifies the user's goal into one of ``quiz`` | ``trivial`` |
``simple`` | ``complex``. When ``quiz``, the LLM also provides the direct
answer (``quiz_response``) to avoid a second LLM call. Loop continuation is
derived structurally inside ``StrangeLoop`` from the checkpoint, not classified.

Prompt bodies live as ``.xml`` fragments under
``soothe.foundation.sloop.prompts.fragments.classifiers``; this module loads
them directly to avoid importing ``soothe.foundation.sloop.prompts`` (circular
import with config).

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


# 4-class intake classification prompt (RFC-630)
INTAKE_CLASSIFICATION_PROMPT = _read_classifier_fragment("intake_classification.xml")

# 4-class intake retry prompt (simplified)
INTAKE_CLASSIFICATION_RETRY_PROMPT = _read_classifier_fragment("intake_classification_retry.xml")

__all__ = [
    "INTAKE_CLASSIFICATION_PROMPT",
    "INTAKE_CLASSIFICATION_RETRY_PROMPT",
]
