"""Tests for PaperScout event system."""

from soothe.core.event_catalog import get_event_registry
from soothe_community.paperscout.events import (
    PAPERSCOUT_EMAIL_SENT,
    PAPERSCOUT_ERROR,
    PAPERSCOUT_PAPER_FOUND,
    PAPERSCOUT_STEP,
    PaperScoutEmailSentEvent,
    PaperScoutErrorEvent,
    PaperScoutPaperFoundEvent,
    PaperScoutStepEvent,
)


def test_events_registered():
    """Test that all PaperScout events are registered."""
    registry = get_event_registry()

    # Check that all event types are registered
    assert PAPERSCOUT_STEP in registry
    assert PAPERSCOUT_PAPER_FOUND in registry
    assert PAPERSCOUT_EMAIL_SENT in registry
    assert PAPERSCOUT_ERROR in registry


def test_step_event():
    """Test PaperScoutStepEvent creation."""
    event = PaperScoutStepEvent(step="data_collection", status="Fetching papers")

    assert event.type == PAPERSCOUT_STEP
    assert event.step == "data_collection"
    assert event.status == "Fetching papers"


def test_paper_found_event():
    """Test PaperScoutPaperFoundEvent creation."""
    event = PaperScoutPaperFoundEvent(
        paper_title="Attention Is All You Need",
        arxiv_id="1706.03762",
        score=7.5,
    )

    assert event.type == PAPERSCOUT_PAPER_FOUND
    assert event.paper_title == "Attention Is All You Need"
    assert event.arxiv_id == "1706.03762"
    assert event.score == 7.5


def test_email_sent_event():
    """Test PaperScoutEmailSentEvent creation."""
    event = PaperScoutEmailSentEvent(
        recipient="user@example.com",
        papers_count=10,
    )

    assert event.type == PAPERSCOUT_EMAIL_SENT
    assert event.recipient == "user@example.com"
    assert event.papers_count == 10


def test_error_event():
    """Test PaperScoutErrorEvent creation."""
    event = PaperScoutErrorEvent(
        error_message="SMTP connection failed",
        step="communication",
    )

    assert event.type == PAPERSCOUT_ERROR
    assert event.error_message == "SMTP connection failed"
    assert event.step == "communication"


def test_event_extra_fields():
    """Test that events allow extra fields."""
    event = PaperScoutStepEvent(
        step="test",
        status="testing",
        extra_field="extra_value",  # Should be allowed
    )

    assert event.extra_field == "extra_value"
