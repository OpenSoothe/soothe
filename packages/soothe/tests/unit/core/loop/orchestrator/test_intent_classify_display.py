"""Display helpers for intake classification progress events (IG-554)."""

from __future__ import annotations

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.sloop.stages.preprocess.intake import (
    INTENT_CLASSIFY_STATUS_LABEL,
    intake_reasoning_event,
    intent_classified_reasoning_event,
    intent_pass_reasoning_events,
    is_displayable_intake_reasoning,
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


def test_intent_pass_reasoning_events_emits_pass1_then_pass2() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="I'll read the readme first.",
        pass1_reasoning="Work request detected.",
        task_complexity=TaskComplexity.SIMPLE,
    )
    events = intent_pass_reasoning_events(intent)
    assert [e[1]["reasoning"] for e in events] == [
        "Work request detected.",
        "I'll read the readme first.",
    ]


def test_intent_pass_reasoning_events_dedupes_identical_text() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="Same line.",
        task_complexity=TaskComplexity.SIMPLE,
    )
    events = intent_pass_reasoning_events(intent, pass1_reasoning="Same line.")
    assert len(events) == 1
    assert events[0][1]["reasoning"] == "Same line."


def test_intake_reasoning_event_skips_fail_safe_placeholders() -> None:
    assert not is_displayable_intake_reasoning("Pre-graph Pass1 error fail-safe")
    assert intake_reasoning_event("Pre-graph Pass1 error fail-safe") is None
    assert intake_reasoning_event("Loop-control phrase; resume via checkpoint") is None
    assert intake_reasoning_event("Work request detected.") is not None


def test_intent_classify_status_label_is_stable() -> None:
    assert INTENT_CLASSIFY_STATUS_LABEL == "Interpreting goal"
