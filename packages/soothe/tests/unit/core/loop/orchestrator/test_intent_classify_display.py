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


def test_intent_pass_reasoning_events_emits_pass2_only() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="I'll read the readme first.",
        task_complexity=TaskComplexity.SIMPLE,
    )
    events = intent_pass_reasoning_events(intent)
    assert [e[1]["reasoning"] for e in events] == ["I'll read the readme first."]


def test_intent_pass_reasoning_events_skips_chitchat() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        reasoning="greeting detected",
        chitchat_response="Hello!",
        task_complexity=TaskComplexity.MINIMAL,
    )
    assert intent_pass_reasoning_events(intent) == []


def test_intent_pass_reasoning_events_skips_empty_reasoning() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        reasoning="",
        task_complexity=TaskComplexity.COMPLEX,
    )
    assert intent_pass_reasoning_events(intent) == []


def test_intake_reasoning_event_skips_empty_text() -> None:
    assert not is_displayable_intake_reasoning("")
    assert not is_displayable_intake_reasoning("   ")
    assert intake_reasoning_event("") is None
    assert intake_reasoning_event("This is a request to read the readme.") is not None


def test_intake_reasoning_event_displays_fail_safe_prose() -> None:
    """Fail-safe verdicts are non-blocking, so their prose reaches the TUI card."""
    assert is_displayable_intake_reasoning(PASS1_FALLBACK_REASONING)
    event = intake_reasoning_event(PASS1_FALLBACK_REASONING)
    assert event is not None
    assert event[1]["reasoning"] == PASS1_FALLBACK_REASONING


def test_intent_classify_status_label_is_stable() -> None:
    assert INTENT_CLASSIFY_STATUS_LABEL == "Interpreting goal"
