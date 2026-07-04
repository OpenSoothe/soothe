"""CronExtractionService — LLM-based schedule extraction (RFC-229).

Extracts structured schedule information from natural language input
using LLM with structured output.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from soothe.foundation.autopilot.engine.schedule_timezone import (
    resolve_schedule_timezone,
    schedule_timezone_label,
)
from soothe.foundation.cron.models import ExtractionResult, ScheduleKind

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config.settings import SootheConfig

logger = logging.getLogger(__name__)


class ExtractionSchema(BaseModel):
    """Structured output schema for LLM extraction.

    Matches ExtractionResult fields for direct conversion.
    """

    task_description: str = Field(description="What the user wants to do (clean, imperative form)")
    schedule_kind: str = Field(
        description="One of: once, delay, at, every, cron",
    )
    schedule_value: str = Field(
        description="Parsed schedule: ISO datetime for once/at, duration for delay/every, cron expression for cron",
    )
    end_condition: str | None = Field(
        default=None,
        description="Optional limit: 'until YYYY-MM-DD' or 'for N days/weeks'",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence 0.0-1.0",
    )


EXTRACTION_PROMPT_TEMPLATE = """Extract schedule information from the user's natural language request.

Input: "{natural_language}"

Analyze the request and extract:
1. **task_description**: What the user wants done. Clean imperative form (e.g., "check the deploy" not "remind me to check the deploy").
2. **schedule_kind**: Determine the type:
   - "once": Single occurrence at unspecified future time
   - "delay": Relative time from now (e.g., "in 2 hours", "after 30 minutes")
   - "at": Specific future datetime (e.g., "tomorrow at 9am", "next Monday morning")
   - "every": Recurring interval (e.g., "every hour", "daily", "every Monday")
   - "cron": Cron-style schedule (e.g., "every weekday at 9am" → "0 9 * * 1-5")
3. **schedule_value**: The parsed time:
   - For "delay": Duration string like "2h", "30m", "1d", "1h30m"
   - For "at" or "once": ISO datetime (YYYY-MM-DDTHH:MM:SS)
   - For "every": Duration string like "1h", "1d", "1w"
   - For "cron": 5-field cron expression (minute hour day month weekday) in the configured local timezone
4. **end_condition**: Optional limit (e.g., "until 2026-06-30", "for 2 weeks")
5. **confidence**: How confident are you in this extraction (0.0-1.0)

Schedule timezone: {schedule_timezone}
Current local date: {current_date}
Current local time: {current_time}

Interpret times like "3am", "9am weekdays", and "tomorrow at noon" in {schedule_timezone}.
Return valid JSON matching the schema. Be precise with datetime calculations.
"""


class CronExtractionService:
    """LLM-based natural language schedule extraction.

    Uses configurable LLM role (default: fast) with structured output.
    Includes retry logic and timeout handling.

    Args:
        config: SootheConfig for LLM factory access.
        model_role: Model role to use (default: fast).
        timeout: Extraction timeout in seconds.
        max_retries: Maximum retry attempts on failure.
    """

    def __init__(
        self,
        config: SootheConfig,
        model_role: str = "fast",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialize extraction service.

        Args:
            config: SootheConfig for LLM factory access.
            model_role: Model role to use (default: fast).
            timeout: Extraction timeout in seconds.
            max_retries: Maximum retry attempts on failure.
        """
        self._config = config
        self._model_role = model_role
        self._timeout = timeout
        self._max_retries = max_retries
        self._model: BaseChatModel | None = None

    def _get_model(self) -> BaseChatModel:
        """Get or create LLM model for extraction.

        Returns:
            BaseChatModel with structured output support.
        """
        if self._model is None:
            factory = self._config.llm_factory
            self._model = factory.create_chat_model(self._model_role)
        return self._model

    async def extract(
        self,
        natural_language: str,
        confidence_threshold: float = 0.5,
    ) -> ExtractionResult:
        """Extract schedule from natural language input.

        Args:
            natural_language: User's natural language request.
            confidence_threshold: Minimum confidence required.

        Returns:
            ExtractionResult with parsed schedule.

        Raises:
            ExtractionError: If extraction fails or confidence below threshold.
        """
        tz_name = self._config.cron.timezone
        tz_label = schedule_timezone_label(tz_name)
        # Anchor prompt clock to configured schedule timezone (defaults to system local).
        now = datetime.now(tz=resolve_schedule_timezone(tz_name))
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            natural_language=natural_language,
            schedule_timezone=tz_label,
            current_date=now.strftime("%Y-%m-%d"),
            current_time=now.strftime("%H:%M:%S"),
        )

        for attempt in range(self._max_retries):
            try:
                result = await self._call_llm(prompt)

                if result.confidence < confidence_threshold:
                    logger.warning(
                        "Extraction confidence %s below threshold %s: %s",
                        result.confidence,
                        confidence_threshold,
                        natural_language,
                    )
                    raise ExtractionError(
                        f"Low confidence ({result.confidence:.2f}). Please rephrase your request more specifically.",
                        result,
                    )

                logger.info(
                    "Extracted schedule: kind=%s value=%s confidence=%.2f",
                    result.schedule_kind,
                    result.schedule_value,
                    result.confidence,
                )
                return result

            except ExtractionError:
                raise
            except Exception as e:
                logger.warning(
                    "Extraction attempt %d/%d failed: %s",
                    attempt + 1,
                    self._max_retries,
                    e,
                )
                if attempt == self._max_retries - 1:
                    raise ExtractionError(
                        f"Extraction failed after {self._max_retries} attempts. "
                        "Please try a simpler format like 'in 2 hours' or 'tomorrow at 9am'.",
                        None,
                    ) from e
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff

        # Should never reach here
        raise ExtractionError("Unexpected extraction failure", None)

    async def _call_llm(self, prompt: str) -> ExtractionResult:
        """Call LLM with structured output.

        Args:
            prompt: Extraction prompt.

        Returns:
            ExtractionResult from LLM response.

        Raises:
            Exception: If LLM call fails.
        """
        from soothe.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )

        model = self._get_model()
        llm_config = llm_rate_limit_config_from(self._config).model_copy(
            update={
                "call_timeout_seconds": self._timeout,
                "call_timeout_max_seconds": max(self._timeout, 60),
            }
        )

        try:

            async def _structured() -> ExtractionResult:
                structured_model = model.with_structured_output(ExtractionSchema)
                result = await structured_model.ainvoke(prompt)
                return self._schema_to_result(result, prompt)

            return await await_with_llm_call_policy(_structured, config=llm_config)

        except TimeoutError:
            raise
        except Exception as e:
            logger.debug("Structured output failed, falling back to JSON parsing: %s", e)

            async def _plain() -> ExtractionResult:
                response = await model.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                return self._parse_json_response(content, prompt)

            return await await_with_llm_call_policy(_plain, config=llm_config)

    def _schema_to_result(
        self,
        schema: ExtractionSchema,
        raw_input: str,
    ) -> ExtractionResult:
        """Convert ExtractionSchema to ExtractionResult.

        Args:
            schema: Pydantic schema from LLM.
            raw_input: Original input for debugging.

        Returns:
            ExtractionResult instance.
        """
        try:
            kind = ScheduleKind(schema.schedule_kind.lower())
        except ValueError:
            logger.warning(
                "Unknown schedule_kind %s, defaulting to 'at'",
                schema.schedule_kind,
            )
            kind = ScheduleKind.AT

        confidence = schema.confidence
        if (
            confidence < 0.5
            and schema.task_description.strip()
            and schema.schedule_kind
            and schema.schedule_value.strip()
        ):
            # Many providers omit ``confidence`` in structured JSON (defaults to 0.0).
            # Treat complete schedule payloads as high confidence.
            confidence = 0.9

        return ExtractionResult(
            description=schema.task_description,
            schedule_kind=kind,
            schedule_value=schema.schedule_value,
            end_condition=schema.end_condition,
            confidence=confidence,
            raw_input=raw_input,
        )

    def _parse_json_response(
        self,
        content: str,
        raw_input: str,
    ) -> ExtractionResult:
        """Parse JSON from LLM content fallback.

        Args:
            content: LLM response content.
            raw_input: Original input for debugging.

        Returns:
            ExtractionResult instance.

        Raises:
            ValueError: If JSON cannot be parsed.
        """
        # Try to extract JSON from content
        try:
            # Direct JSON parse
            data = json.loads(content)
        except json.JSONDecodeError:
            # Look for JSON block
            import re

            match = re.search(r"\{[^{}]*\}", content)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Cannot parse JSON from response: {content[:100]}")

        schema = ExtractionSchema(**data)
        return self._schema_to_result(schema, raw_input)


class AutopilotDisabledError(Exception):
    """Cron submission rejected because autopilot scheduling is disabled.

    Attributes:
        message: User-facing guidance to enable autopilot.
    """

    def __init__(self, message: str) -> None:
        """Initialize autopilot-disabled error.

        Args:
            message: User-facing guidance.
        """
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ExtractionError(Exception):
    """Extraction failure with optional partial result.

    Attributes:
        message: Error message for user.
        partial_result: Partial extraction if available.
    """

    def __init__(
        self,
        message: str,
        partial_result: ExtractionResult | None,
    ) -> None:
        """Initialize extraction error.

        Args:
            message: Error message for user.
            partial_result: Partial extraction if available.
        """
        super().__init__(message)
        self.message = message
        self.partial_result = partial_result

    def __str__(self) -> str:
        """Return error message."""
        return self.message
