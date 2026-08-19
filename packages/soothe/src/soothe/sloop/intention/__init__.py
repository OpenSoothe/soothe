"""Intent classification module (RFC-225, RFC-630 pass1, RFC-904).

Pass 1 (social vs task) via ``IntakePass1Classifier``.
Pass 2 scope classification is removed; tasks enter do-or-decompose.
"""

from __future__ import annotations

from .classifier import IntentClassifier
from .models import (
    IntakeLabel,
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass2LLMResult,
    IntakeScope,
    IntentClassification,
    ResponseLanguage,
    RoutingClassification,
    TaskComplexity,
    build_loop_routing_classification,
    intent_classification_from_intake_scope,
    intent_classification_from_pass1_task,
    intent_classification_from_pass2,
    normalize_response_language,
    parse_intake_scope,
)
from .pass1_classifier import IntakePass1Classifier, build_pass1_task_fallback
from .two_pass_coordinator import TwoPassIntakeCoordinator, TwoPassIntakeResult

__all__ = [
    "IntakeLabel",
    "IntentClassifier",
    "IntakePass1Classifier",
    "IntakePass1Confidence",
    "IntakePass1LLMResult",
    "IntakePass2LLMResult",
    "IntakeScope",
    "IntentClassification",
    "ResponseLanguage",
    "RoutingClassification",
    "TaskComplexity",
    "TwoPassIntakeCoordinator",
    "TwoPassIntakeResult",
    "build_loop_routing_classification",
    "build_pass1_task_fallback",
    "intent_classification_from_intake_scope",
    "intent_classification_from_pass1_task",
    "intent_classification_from_pass2",
    "normalize_response_language",
    "parse_intake_scope",
]
