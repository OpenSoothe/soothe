"""Unit tests for PresentationEngine action deduplication (IG-143)."""

from soothe.ux.shared.presentation_engine import PresentationEngine


def test_should_emit_action_deduplicates_identical_text():
    """Verify deduplication of same action within 5s."""
    engine = PresentationEngine()

    # First emission should pass
    assert engine.should_emit_action(action_text="Analyzing files (80% sure)", now_s=100.0)

    # Same text within 5s should be suppressed
    assert not engine.should_emit_action(action_text="Analyzing files (80% sure)", now_s=102.0)

    # Same text after 5s should pass
    assert engine.should_emit_action(action_text="Analyzing files (80% sure)", now_s=106.0)


def test_should_emit_action_normalizes_confidence_suffix():
    """Verify stripping '(XX% sure)' and '(XX% confident)' for comparison."""
    engine = PresentationEngine()

    # Emit with 'sure' suffix
    assert engine.should_emit_action(action_text="Working (80% sure)", now_s=100.0)

    # Same text with 'confident' suffix should be suppressed (normalized identical)
    assert not engine.should_emit_action(action_text="Working (80% confident)", now_s=101.0)


def test_should_emit_action_respects_5s_window():
    """Verify time-based deduplication window."""
    engine = PresentationEngine()

    # Emit at t=0
    assert engine.should_emit_action(action_text="Action A", now_s=100.0)

    # Within 5s: suppressed
    assert not engine.should_emit_action(action_text="Action A", now_s=104.9)

    # At exactly 5s: allowed
    assert engine.should_emit_action(action_text="Action A", now_s=105.0)


def test_normalize_action_removes_whitespace():
    """Verify text normalization for deduplication."""
    engine = PresentationEngine()

    # Emit with extra whitespace
    assert engine.should_emit_action(action_text="  Analyzing   files  (80% sure)", now_s=100.0)

    # Normalized version should be suppressed
    assert not engine.should_emit_action(action_text="Analyzing files (80% sure)", now_s=101.0)


def test_reset_turn_clears_action_state():
    """Verify reset_turn clears action dedup state."""
    engine = PresentationEngine()

    # Emit action
    engine.should_emit_action(action_text="Working (80% sure)", now_s=100.0)

    # Reset turn
    engine.reset_turn()

    # State should be cleared
    assert engine._state.last_action_text == ""
    assert engine._state.last_action_time == 0.0

    # Same action should now be allowed again
    assert engine.should_emit_action(action_text="Working (80% sure)", now_s=101.0)
