"""Failure intent classification for reflection (IG-433)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from soothe.config.models import FailureIntentConfig
from soothe.utils.llm.structured_invoke import invoke_structured_chat_typed

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

FailureCategory = Literal[
    "missing_prerequisite",
    "permission_denied",
    "resource_unavailable",
    "syntax_error",
    "logic_error",
    "timeout",
    "unknown",
]

SuggestedAction = Literal["create_prerequisite", "retry", "escalate", "skip"]

_KEYWORD_RULES: list[tuple[FailureCategory, frozenset[str], float, SuggestedAction]] = [
    (
        "missing_prerequisite",
        frozenset(
            {
                "missing",
                "not found",
                "not installed",
                "not available",
                "not configured",
                "no such",
                "does not exist",
                "cannot find",
                "dependency",
                "prerequisite",
            }
        ),
        0.85,
        "create_prerequisite",
    ),
    (
        "permission_denied",
        frozenset(
            {"permission denied", "access denied", "forbidden", "unauthorized", "not allowed"}
        ),
        0.9,
        "escalate",
    ),
    (
        "resource_unavailable",
        frozenset({"out of memory", "no space", "disk full", "connection refused", "unavailable"}),
        0.8,
        "retry",
    ),
    (
        "syntax_error",
        frozenset({"syntaxerror", "syntax error", "parse error", "invalid syntax"}),
        0.85,
        "retry",
    ),
    (
        "logic_error",
        frozenset({"assertionerror", "valueerror", "typeerror", "runtime error", "exception"}),
        0.75,
        "retry",
    ),
    (
        "timeout",
        frozenset({"timeout", "timed out", "deadline exceeded"}),
        0.9,
        "retry",
    ),
]


class FailureIntent(BaseModel):
    """Classified failure intent from step output text."""

    category: FailureCategory
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_action: SuggestedAction
    extracted_entities: list[str] = Field(default_factory=list)


def _extract_entities(text: str) -> list[str]:
    """Extract quoted strings and file-like tokens from failure text."""
    entities: list[str] = []
    entities.extend(match.group(1) for match in re.finditer(r'["\']([^"\']{2,80})["\']', text))
    entities.extend(match.group(0) for match in re.finditer(r"\b[\w\-./]+\.\w{2,5}\b", text))
    return list(dict.fromkeys(entities))[:10]


def classify_failure_intent_keyword(text: str) -> FailureIntent:
    """Fast keyword-based failure intent classification."""
    lowered = (text or "").lower()
    best_category: FailureCategory = "unknown"
    best_confidence = 0.4
    best_action: SuggestedAction = "retry"

    for category, keywords, confidence, action in _KEYWORD_RULES:
        if any(kw in lowered for kw in keywords):
            if confidence > best_confidence:
                best_category = category
                best_confidence = confidence
                best_action = action

    return FailureIntent(
        category=best_category,
        confidence=best_confidence,
        suggested_action=best_action,
        extracted_entities=_extract_entities(text),
    )


async def classify_failure_intent_async(
    text: str,
    model: BaseChatModel | None,
    *,
    config: FailureIntentConfig | None = None,
    soothe_config: Any | None = None,
) -> FailureIntent:
    """Classify failure intent with keyword fast-path and optional LLM refinement."""
    cfg = config or FailureIntentConfig()
    keyword_result = classify_failure_intent_keyword(text)

    if not cfg.enabled:
        return keyword_result

    if keyword_result.confidence >= cfg.llm_confidence_threshold or model is None:
        return keyword_result

    try:
        from langchain_core.messages import HumanMessage

        from soothe.utils.observability.langfuse import build_traced_config

        prompt = (
            "Classify this tool/step failure for an autonomous agent.\n"
            f"Failure text:\n{text[:2000]}\n"
            "\nReturn category, confidence 0-1, suggested_action, and extracted_entities."
        )
        invoke_config = build_traced_config(
            soothe_config,
            purpose="failure_intent_classify",
            component="loop.failure_intent",
            phase="reflect",
            run_name="soothe:failure-intent",
        )
        return await invoke_structured_chat_typed(
            model,
            [HumanMessage(content=prompt)],
            FailureIntent,
            config=invoke_config,
        )
    except Exception:
        logger.debug("LLM failure intent classification failed", exc_info=True)
        return keyword_result


def is_missing_prerequisite_intent(intent: FailureIntent) -> bool:
    """Return True when failure should spawn a prerequisite goal."""
    return (
        intent.category == "missing_prerequisite"
        and intent.suggested_action == "create_prerequisite"
    )
