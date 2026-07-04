"""Intent classification module (RFC-225, RFC-630).

3-class LLM intake (``trivial`` | ``simple`` | ``complex``). Loop continuation
is derived structurally inside ``StrangeLoop`` from the loaded checkpoint.
"""

from __future__ import annotations

from .classifier import IntentClassifier
from .identity_messages import build_intake_identity_message
from .models import (
    IntentClassification,
    RoutingClassification,
    TaskComplexity,
    build_loop_routing_classification,
)

__all__ = [
    "IntentClassifier",
    "IntentClassification",
    "RoutingClassification",
    "TaskComplexity",
    "build_intake_identity_message",
    "build_loop_routing_classification",
]
