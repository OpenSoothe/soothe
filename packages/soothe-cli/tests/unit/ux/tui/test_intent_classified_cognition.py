"""Intent-classify reasoning renders as a cognition card on the TUI."""

from __future__ import annotations

from soothe_sdk.display import card_binder
from soothe_sdk.display.transcript_types import MessageType

from soothe_cli.tui.widgets.messages import CognitionReasonMessage


def test_intent_classified_reasoning_cognition_message() -> None:
    widget = CognitionReasonMessage(
        status="",
        iteration=0,
        plan_reasoning="I'll inspect the repo to map the architecture.",
        id="intent-test",
    )
    header = widget._plan_header_content()
    assert "I'll inspect the repo" in str(header)


def test_card_binder_maps_intent_classified_to_cognition_reason() -> None:
    msg = card_binder.convert_event_to_message_data(
        {
            "kind": "event",
            "data": {
                "type": "soothe.cognition.intent.classified",
                "reasoning": "Let me search the web for today's weather.",
                "intent_type": "agentic",
            },
        }
    )
    assert msg is not None
    assert msg.type == MessageType.COGNITION_REASON
    assert msg.cognition_plan_strategy == "Let me search the web for today's weather."
