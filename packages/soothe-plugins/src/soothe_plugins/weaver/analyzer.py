"""RequirementAnalyzer -- LLM-based capability extraction (RFC-0005) -- community edition."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .models import CapabilitySignature

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_ANALYSIS_PROMPT = """\
You are analysing a user request to determine what kind of specialist agent \
is needed. Extract a structured capability signature.

User request:
{request}

Output valid JSON with these fields:
{{
  "description": "One-paragraph summary of what the agent should do",
  "required_capabilities": ["capability_keyword_1", "capability_keyword_2"],
  "constraints": ["constraint_1"],
  "expected_input": "What the agent receives from the user",
  "expected_output": "What the agent should produce"
}}

Be specific about capabilities. Use lowercase snake_case for capability keywords."""


class RequirementAnalyzer:
    """Extracts a structured capability signature from a user request via LLM.

    Args:
        model: Chat model for analysis.
    """

    def __init__(self, model: BaseChatModel) -> None:
        """Initialize the requirement analyzer.

        Args:
            model: Chat model for analysis.
        """
        self._model = model

    async def analyze(self, request: str) -> CapabilitySignature:
        """Extract a ``CapabilitySignature`` from the user request.

        Args:
            request: Raw user request text.

        Returns:
            Structured capability signature.
        """
        prompt = _ANALYSIS_PROMPT.format(request=request)

        try:
            resp = await self._model.ainvoke([{"role": "user", "content": prompt}])
            content = str(resp.content)
            parsed = json.loads(content)
            return CapabilitySignature(**parsed)
        except json.JSONDecodeError:
            logger.warning("Failed to parse analysis response as JSON, using fallback")
            return CapabilitySignature(
                description=request,
                required_capabilities=[],
                expected_input="user request",
                expected_output="task result",
            )
        except Exception:
            logger.exception("Requirement analysis failed")
            return CapabilitySignature(
                description=request,
                required_capabilities=[],
                expected_input="user request",
                expected_output="task result",
            )
