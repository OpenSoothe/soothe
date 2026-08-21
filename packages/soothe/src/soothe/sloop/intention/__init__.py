"""Intent classification module (RFC-225, RFC-630, RFC-904).

Intake classification (social vs task + task complexity + short description)
via ``IntakeClassifier``; the facade ``IntentClassifier`` runs in the graph
INTAKE node with full CE ledger projection. Fallback classification runs
when the classifier is disabled or the call fails.
"""

from __future__ import annotations

from .classifier import IntentClassifier
from .coordinator import IntakeCoordinator, IntakeResult
from .intake_classifier import IntakeClassifier, build_intake_task_fallback
from .models import (
    IntakeConfidence,
    IntakeLabel,
    IntakeLLMResult,
    IntakeScope,
    IntentClassification,
    ResponseLanguage,
    RoutingClassification,
    TaskComplexity,
    build_loop_routing_classification,
    intent_classification_from_intake,
    intent_classification_from_intake_scope,
    normalize_response_language,
    parse_intake_scope,
)

__all__ = [
    "IntakeLabel",
    "IntentClassifier",
    "IntakeClassifier",
    "IntakeConfidence",
    "IntakeLLMResult",
    "IntakeScope",
    "IntentClassification",
    "ResponseLanguage",
    "RoutingClassification",
    "TaskComplexity",
    "IntakeCoordinator",
    "IntakeResult",
    "build_loop_routing_classification",
    "build_intake_task_fallback",
    "intent_classification_from_intake",
    "intent_classification_from_intake_scope",
    "normalize_response_language",
    "parse_intake_scope",
]
