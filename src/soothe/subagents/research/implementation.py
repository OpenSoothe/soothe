"""Research subagent implementation.

Converts the research capability from a tool to a subagent following RFC-0021.
The subagent wraps the InquiryEngine and provides a CompiledSubAgent interface.
"""

from __future__ import annotations

import logging
from operator import add
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .engine import build_inquiry_engine
from .protocol import InquiryConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.graph import CompiledStateGraph

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class ResearchState(TypedDict):
    """State schema for research subagent."""

    messages: Annotated[list, add_messages]
    research_topic: str
    domain: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_loops: int
    loop_count: int


def create_research_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> CompiledStateGraph:
    """Create research subagent.

    Args:
        model: LLM for research operations.
        config: Soothe configuration.
        context: Context with work_dir and settings.

    Returns:
        Compiled LangGraph subagent implementing research workflow.
    """
    work_dir = context.get("work_dir", "")
    max_loops = context.get("max_loops", 3)
    domain = context.get("domain", "auto")

    # Build sources based on domain
    sources = _build_sources(domain, config, work_dir)

    # Create inquiry config
    inquiry_config = InquiryConfig(max_loops=max_loops)

    # Build and return the engine
    return build_inquiry_engine(model, sources, inquiry_config, _domain=domain)


def _build_sources(
    domain: str,
    config: SootheConfig,
    work_dir: str,
) -> list[Any]:
    """Build information sources for the given domain.

    Args:
        domain: Source domain hint.
        config: Soothe configuration.
        work_dir: Working directory.

    Returns:
        List of InformationSource instances.
    """
    from .sources.academic import AcademicSource
    from .sources.browser import BrowserSource
    from .sources.cli import CLISource
    from .sources.document import DocumentSource
    from .sources.filesystem import FilesystemSource
    from .sources.web import WebSource

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

    # auto domain (default)
    return [
        WebSource(config=config),
        AcademicSource(),
        FilesystemSource(work_dir=work_dir),
        CLISource(workspace_root=work_dir),
        DocumentSource(),
    ]
