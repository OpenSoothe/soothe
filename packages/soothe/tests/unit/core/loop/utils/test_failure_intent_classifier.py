"""Tests for failure intent classifier (IG-433)."""

from soothe.config.models import FailureIntentConfig
from soothe.foundation.sloop.utils.failure_intent_classifier import (
    classify_failure_intent_keyword,
    is_missing_prerequisite_intent,
)


class TestFailureIntentClassifier:
    def test_missing_prerequisite_keywords(self) -> None:
        intent = classify_failure_intent_keyword("library not found: libfoo")
        assert intent.category == "missing_prerequisite"
        assert is_missing_prerequisite_intent(intent)

    def test_permission_denied(self) -> None:
        intent = classify_failure_intent_keyword("Error: permission denied")
        assert intent.category == "permission_denied"
        assert intent.suggested_action == "escalate"

    def test_unknown_failure(self) -> None:
        intent = classify_failure_intent_keyword("something unexpected happened")
        assert intent.category == "unknown"

    def test_disabled_config_uses_legacy_in_reflection(self) -> None:
        from soothe.foundation.sloop.utils.reflection import _failure_text_indicates_prerequisite

        cfg = FailureIntentConfig(enabled=False)
        assert _failure_text_indicates_prerequisite("library not found", failure_config=cfg)
