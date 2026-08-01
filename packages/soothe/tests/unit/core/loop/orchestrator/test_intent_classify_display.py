"""Display helpers for intake classification progress events (IG-554)."""

from __future__ import annotations

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.sloop.intention.pass1_classifier import PASS1_FALLBACK_REASONING
from soothe.sloop.stages.preprocess.intake import (
    INTENT_CLASSIFY_STATUS_LABEL,
    intake_reasoning_event,
    intent_pass_reasoning_events,
    is_displayable_intake_reasoning,
)


def test_intent_pass_reasoning_events_emits_pass1_then_pass2() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="I'll read the readme first.",
        pass1_reasoning="This is a request to read the readme.",
        task_complexity=TaskComplexity.SIMPLE,
    )
    events = intent_pass_reasoning_events(intent)
    assert [e[1]["reasoning"] for e in events] == [
        "This is a request to read the readme.",
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


def test_intent_pass_reasoning_events_skips_chitchat() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        reasoning="greeting detected",
        pass1_reasoning="greeting detected",
        chitchat_response="Hello!",
        task_complexity=TaskComplexity.MINIMAL,
    )
    assert intent_pass_reasoning_events(intent) == []


def test_intent_pass_reasoning_events_pass1_only_when_pass2_empty() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="",
        task_complexity=TaskComplexity.SIMPLE,
    )
    events = intent_pass_reasoning_events(
        intent, pass1_reasoning="This is a request to read the readme."
    )
    assert [e[1]["reasoning"] for e in events] == ["This is a request to read the readme."]


def test_intent_pass_reasoning_events_skips_empty_reasoning() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        reasoning="",
        task_complexity=TaskComplexity.COMPLEX,
    )
    assert intent_pass_reasoning_events(intent, pass1_reasoning="") == []


def test_intake_reasoning_event_skips_structural_bypass_markers() -> None:
    assert not is_displayable_intake_reasoning("Loop-control phrase; resume via checkpoint")
    assert intake_reasoning_event("Loop-control phrase; resume via checkpoint") is None
    assert intake_reasoning_event("This is a request to read the readme.") is not None


def test_intake_reasoning_event_displays_fail_safe_prose() -> None:
    """Fail-safe verdicts are non-blocking, so their prose reaches the TUI card."""
    assert is_displayable_intake_reasoning(PASS1_FALLBACK_REASONING)
    event = intake_reasoning_event(PASS1_FALLBACK_REASONING)
    assert event is not None
    assert event[1]["reasoning"] == PASS1_FALLBACK_REASONING


def test_intent_classify_status_label_is_stable() -> None:
    assert INTENT_CLASSIFY_STATUS_LABEL == "Interpreting goal"
