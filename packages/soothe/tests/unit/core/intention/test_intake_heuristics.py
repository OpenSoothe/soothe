"""Tests for deterministic intake heuristics (RFC-630)."""

from __future__ import annotations

from soothe.foundation.sloop.intention.intake_heuristics import classify_intake_heuristic
from soothe.foundation.sloop.intention.models import IntakeLabel


class TestClassifyIntakeHeuristic:
    def test_weather_query_is_trivial(self) -> None:
        result = classify_intake_heuristic("北京今天的天气")
        assert result is not None
        assert result.intake_label == IntakeLabel.TRIVIAL
        assert result.goal_description == "北京今天的天气"

    def test_weather_english_is_trivial(self) -> None:
        result = classify_intake_heuristic("weather in London today")
        assert result is not None
        assert result.intake_label == IntakeLabel.TRIVIAL

    def test_greeting_is_trivial(self) -> None:
        result = classify_intake_heuristic("你好")
        assert result is not None
        assert result.intake_label == IntakeLabel.TRIVIAL

    def test_complex_refactor_not_heuristic(self) -> None:
        assert classify_intake_heuristic("refactor the persistence layer for weather module") is None

    def test_long_weather_plan_not_heuristic(self) -> None:
        query = "天气 " * 40
        assert classify_intake_heuristic(query) is None

    def test_clawhub_query_is_trivial(self) -> None:
        result = classify_intake_heuristic("is there skill of drawio on claw hub")
        assert result is not None
        assert result.intake_label == IntakeLabel.TRIVIAL
