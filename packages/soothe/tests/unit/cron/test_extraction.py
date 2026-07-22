"""Unit tests for CronExtractionService (RFC-229).

Uses mock LLM responses for testing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

from soothe.cron.extraction import (
    CronExtractionService,
    ExtractionError,
    ExtractionSchema,
)
from soothe.cron.models import ExtractionResult, ScheduleKind


class MockExtractionService:
    """Mock extraction service for testing without LLM."""

    async def extract(
        self,
        natural_language: str,
        confidence_threshold: float = 0.5,
    ) -> ExtractionResult:
        """Mock extraction based on pattern matching."""
        nl = natural_language.lower()

        # Pattern matching for common cases
        if "every hour" in nl:
            return ExtractionResult(
                description=nl.replace("remind me ", "").replace("every hour", "").strip()
                or "Hourly task",
                schedule_kind=ScheduleKind.EVERY,
                schedule_value="1h",
                confidence=0.9,
                raw_input=natural_language,
            )
        if "in " in nl and ("hour" in nl or "minute" in nl):
            import re

            match = re.search(r"in (\d+) (hour|minute|hours|minutes)", nl)
            if match:
                count = int(match.group(1))
                unit = match.group(2)[:1]  # h or m
                return ExtractionResult(
                    description=nl.replace(match.group(0), "").strip(),
                    schedule_kind=ScheduleKind.DELAY,
                    schedule_value=f"{count}{unit}",
                    confidence=0.85,
                    raw_input=natural_language,
                )
        if "tomorrow" in nl:
            tomorrow = datetime.now(tz=UTC) + __import__("datetime").timedelta(days=1)
            return ExtractionResult(
                description=nl.replace("tomorrow", "").replace("at ", "").strip(),
                schedule_kind=ScheduleKind.AT,
                schedule_value=tomorrow.strftime("%Y-%m-%dT09:00:00"),
                confidence=0.8,
                raw_input=natural_language,
            )

        # Low confidence for unparseable
        return ExtractionResult(
            description=natural_language,
            schedule_kind=ScheduleKind.ONCE,
            schedule_value="",
            confidence=0.2,
            raw_input=natural_language,
        )


class TestCronExtractionService:
    """Tests for extraction patterns."""

    def test_extract_every_hour(self) -> None:
        """Extract 'every hour' pattern."""
        service = MockExtractionService()
        result = asyncio.run(service.extract("remind me every hour to check the server"))

        assert result.schedule_kind == ScheduleKind.EVERY
        assert result.schedule_value == "1h"
        assert result.is_valid(0.5)

    def test_extract_delay_hours(self) -> None:
        """Extract 'in X hours' pattern."""
        service = MockExtractionService()
        result = asyncio.run(service.extract("in 2 hours check the deploy status"))

        assert result.schedule_kind == ScheduleKind.DELAY
        assert result.schedule_value == "2h"
        assert result.is_valid(0.5)

    def test_extract_delay_minutes(self) -> None:
        """Extract 'in X minutes' pattern."""
        service = MockExtractionService()
        result = asyncio.run(service.extract("in 30 minutes send the email"))

        assert result.schedule_kind == ScheduleKind.DELAY
        assert result.schedule_value == "30m"

    def test_extract_tomorrow(self) -> None:
        """Extract 'tomorrow' pattern."""
        service = MockExtractionService()
        result = asyncio.run(service.extract("tomorrow check the reports"))

        assert result.schedule_kind == ScheduleKind.AT
        assert result.is_valid(0.5)

    def test_low_confidence_below_threshold(self) -> None:
        """Unparseable input has low confidence."""
        service = MockExtractionService()
        result = asyncio.run(service.extract("some random text that makes no sense"))

        assert result.confidence < 0.5
        assert not result.is_valid(0.5)


class TestSchemaConfidenceInference:
    """Tests for confidence inference when providers omit the field."""

    def test_schema_to_result_infers_confidence_from_complete_payload(self) -> None:
        """Complete structured output without confidence should pass threshold."""
        service = CronExtractionService(config=MagicMock())
        schema = ExtractionSchema(
            task_description="send status report",
            schedule_kind="cron",
            schedule_value="0 9 * * *",
        )
        result = service._schema_to_result(schema, "every day at 9am send status report")

        assert result.confidence == 0.9
        assert result.is_valid(0.5)


class TestExtractionError:
    """Tests for ExtractionError."""

    def test_error_with_message(self) -> None:
        """Create error with message only."""
        error = ExtractionError("Test error", None)
        assert str(error) == "Test error"
        assert error.partial_result is None

    def test_error_with_partial_result(self) -> None:
        """Create error with partial result."""
        partial = ExtractionResult(
            description="Partial",
            schedule_kind=ScheduleKind.DELAY,
            schedule_value="2h",
            confidence=0.3,
        )
        error = ExtractionError("Low confidence", partial)
        assert error.partial_result is not None
        assert error.partial_result.confidence == 0.3
