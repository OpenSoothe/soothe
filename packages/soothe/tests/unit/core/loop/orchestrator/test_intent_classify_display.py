"""Display helpers for intake classification progress events (IG-554)."""

from __future__ import annotations

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.sloop.nodes.intent_classify import (
    INTENT_CLASSIFY_STATUS_LABEL,
    intent_classified_reasoning_event,
)


def test_intent_classified_reasoning_event_prefers_pass2() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="I'll read the readme first.",
        task_complexity=TaskComplexity.SIMPLE,
    )
    event = intent_classified_reasoning_event(
        intent,
        pass1_reasoning="Work request detected.",
    )
    assert event is not None
    assert event[1]["reasoning"] == "I'll read the readme first."


def test_intent_classified_reasoning_event_falls_back_to_pass1() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="",
        task_complexity=TaskComplexity.SIMPLE,
    )
    event = intent_classified_reasoning_event(
        intent,
        pass1_reasoning="Work request detected.",
    )
    assert event is not None
    assert event[1]["reasoning"] == "Work request detected."


def test_intent_classified_reasoning_event_skips_chitchat() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        reasoning="greeting detected",
        chitchat_response="Hello!",
        task_complexity=TaskComplexity.MINIMAL,
    )
    assert intent_classified_reasoning_event(intent) is None


def test_intent_classified_reasoning_event_skips_empty_reasoning() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        reasoning="",
        task_complexity=TaskComplexity.COMPLEX,
    )
    assert intent_classified_reasoning_event(intent, pass1_reasoning="") is None


def test_intent_classify_status_label_is_stable() -> None:
    assert INTENT_CLASSIFY_STATUS_LABEL == "Interpreting goal"
