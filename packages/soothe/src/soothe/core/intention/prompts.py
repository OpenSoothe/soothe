"""LLM prompts for intent classification (RFC-225).

Two-value classification with piggybacked quiz answer: the LLM decides whether
a query is a simple quiz (greeting, thanks, static trivia answerable without
tools) or requires the agentic loop. When quiz, the LLM also provides the
direct answer (``quiz_response``) to avoid a second LLM call. Loop continuation
is derived structurally inside ``AgentLoop`` from the checkpoint, not classified.

Prompt bodies live as ``.xml`` fragments under
``soothe.core.prompts.fragments.classifiers``; this module re-exports them
under their established public names so callers (``intention.classifier``)
remain unchanged.

XML structure:
- <intent_instructions>: Static content (classification rules, JSON schema)
- <intent_inputs> (retry only): Dynamic runtime fields as flat XML elements
  - <current_time>, <current_query>: Runtime context
"""

from __future__ import annotations

from soothe.core.prompts.fragments import (
    INTENT_CLASSIFICATION_PROMPT_FRAGMENT,
    INTENT_CLASSIFICATION_RETRY_PROMPT_FRAGMENT,
)

# Intent classification prompt (quiz detection only; continue/new_goal decided structurally)
INTENT_CLASSIFICATION_PROMPT = INTENT_CLASSIFICATION_PROMPT_FRAGMENT

# Retry prompt (simplified)
INTENT_CLASSIFICATION_RETRY_PROMPT = INTENT_CLASSIFICATION_RETRY_PROMPT_FRAGMENT

__all__ = [
    "INTENT_CLASSIFICATION_PROMPT",
    "INTENT_CLASSIFICATION_RETRY_PROMPT",
]
