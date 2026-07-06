"""Intent classification module (RFC-225, RFC-630, IG-554).

Two-pass LLM intake (RFC-630 IG-554):
- Pass 1 (social vs task) via ``IntakePass1Classifier``.
- Pass 2 (scope: trivial|simple|complex) via ``IntakePass2Classifier``.
- Full orchestration via ``TwoPassIntakeCoordinator``.

Loop continuation is derived structurally inside ``StrangeLoop`` from the
loaded checkpoint, not classified here.
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
    RoutingClassification,
    TaskComplexity,
    build_loop_routing_classification,
)
from .pass1_classifier import IntakePass1Classifier
from .pass2_classifier import IntakePass2Classifier
from .two_pass_coordinator import TwoPassIntakeCoordinator, TwoPassIntakeResult

__all__ = [
    "IntakeLabel",
    "IntentClassifier",
    "IntakePass1Classifier",
    "IntakePass1Confidence",
    "IntakePass1LLMResult",
    "IntakePass2Classifier",
    "IntakePass2LLMResult",
    "IntakeScope",
    "IntentClassification",
    "RoutingClassification",
    "TaskComplexity",
    "TwoPassIntakeCoordinator",
    "TwoPassIntakeResult",
    "build_loop_routing_classification",
]
