"""Inquiry tool -- exposes the InquiryEngine as a direct tool for the main agent.

This is the unified "deep research" capability.  The main agent uses this
tool when it needs to *research* something (as opposed to directly *acting*
with file_edit, cli, etc.).  The ``domain`` parameter lets the LLM hint
at which information sources are most relevant, while the InquiryEngine
handles source routing internally.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, ClassVar

from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)


class InquiryTool(BaseTool):
    """Deep research tool backed by the tool-agnostic InquiryEngine.

    Iteratively searches, analyses, and synthesises information from
    multiple sources (web, academic, filesystem, CLI, documents).
    """

    name: str = "inquiry"
    description: str = (
        "Deep research tool that iteratively searches, analyses, and synthesises "
        "information from multiple sources. Use when a question requires thorough "
        "investigation beyond a single search. "
        "Inputs: `topic` (required, the research question), "
        "`domain` (optional, one of 'auto', 'web', 'code', 'deep'; default 'auto'). "
        "- 'web': Internet research (web search + academic papers). "
        "- 'code': Codebase exploration (filesystem + CLI tools). "
        "- 'deep': All sources combined for comprehensive research. "
        "- 'auto': Automatically selects sources based on the topic. "
        "Returns a comprehensive answer with citations."
    )

    soothe_config: Any = Field(default=None, exclude=True)
    """Soothe config for source and model resolution."""

    work_dir: str = Field(default="")
    """Working directory for filesystem/CLI sources."""

    max_loops: int = Field(default=3)
    """Maximum research reflection loops."""

    _engine_cache: ClassVar[dict[str, Any]] = {}

    def _resolve_model(self) -> Any:
        """Resolve the LLM model for the inquiry engine."""
        from langchain.chat_models import init_chat_model

        if self.soothe_config:
            model_str = self.soothe_config.resolve_model("default")
        else:
            model_str = os.environ.get("SOOTHE_DEFAULT_MODEL", "openai:gpt-4o-mini")

        model_kwargs: dict[str, Any] = {}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            model_kwargs["base_url"] = base_url
            model_kwargs["use_responses_api"] = False

        return init_chat_model(model_str, **model_kwargs)

    def _build_sources(self, domain: str) -> list:
        """Build the appropriate source list for the given domain.

        Args:
            domain: Source domain hint.

        Returns:
            List of InformationSource instances.
        """
        from soothe.inquiry.sources.academic import AcademicSource
        from soothe.inquiry.sources.browser import BrowserSource
        from soothe.inquiry.sources.cli import CLISource
        from soothe.inquiry.sources.document import DocumentSource
        from soothe.inquiry.sources.filesystem import FilesystemSource
        from soothe.inquiry.sources.web import WebSource

        work_dir = self.work_dir
        config = self.soothe_config

        if domain == "web":
            return [WebSource(config=config), AcademicSource()]
        if domain == "code":
            return [FilesystemSource(work_dir=work_dir), CLISource(workspace_root=work_dir)]
        if domain == "deep":
            return [
                WebSource(config=config),
                AcademicSource(),
                FilesystemSource(work_dir=work_dir),
                CLISource(workspace_root=work_dir),
                DocumentSource(),
                BrowserSource(config=config),
            ]

        return [
            WebSource(config=config),
            AcademicSource(),
            FilesystemSource(work_dir=work_dir),
            CLISource(workspace_root=work_dir),
            DocumentSource(),
        ]

    def _build_engine(self, domain: str) -> Any:
        """Build (or retrieve cached) InquiryEngine for the domain."""
        from soothe.inquiry.engine import build_inquiry_engine
        from soothe.inquiry.protocol import InquiryConfig

        cache_key = domain
        if cache_key in self._engine_cache:
            return self._engine_cache[cache_key]

        model = self._resolve_model()
        sources = self._build_sources(domain)
        inquiry_config = InquiryConfig(max_loops=self.max_loops)

        engine = build_inquiry_engine(model, sources, inquiry_config, _domain=domain)
        self._engine_cache[cache_key] = engine
        return engine

    def _run(self, topic: str, domain: str = "auto") -> str:
        """Execute deep research on the given topic.

        Args:
            topic: The research question or topic.
            domain: Source domain hint ('auto', 'web', 'code', 'deep').

        Returns:
            Comprehensive research answer with citations.
        """
        engine = self._build_engine(domain)
        try:
            result = engine.invoke(
                {
                    "research_topic": topic,
                    "domain": domain,
                    "messages": [],
                }
            )
            return result.get("answer", "Research completed but no answer was generated.")
        except Exception:
            logger.exception("Inquiry engine failed for topic: %s", topic)
            return f"Research failed for topic: {topic}. Please try a more specific query."

    async def _arun(self, topic: str, domain: str = "auto") -> str:
        """Async deep research execution."""
        engine = self._build_engine(domain)
        try:
            result = await asyncio.to_thread(
                engine.invoke,
                {"research_topic": topic, "domain": domain, "messages": []},
            )
            return result.get("answer", "Research completed but no answer was generated.")
        except Exception:
            logger.exception("Inquiry engine failed for topic: %s", topic)
            return f"Research failed for topic: {topic}. Please try a more specific query."


def create_inquiry_tools(
    config: Any | None = None,
    work_dir: str = "",
) -> list[BaseTool]:
    """Create inquiry tool instances.

    Args:
        config: Optional Soothe config.
        work_dir: Working directory for filesystem/CLI sources.

    Returns:
        List containing the InquiryTool.
    """
    return [
        InquiryTool(soothe_config=config, work_dir=work_dir),
    ]
