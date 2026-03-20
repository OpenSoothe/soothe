"""Research subagent -- iterative web research specialist.

Now a thin wrapper around the tool-agnostic InquiryEngine.
Configures the engine with web and academic sources for
backward-compatible web research behaviour.

Legacy graph builder is preserved as ``_build_research_graph`` for
existing callers, but ``create_research_subagent`` now uses the
InquiryEngine by default.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Description (unchanged -- kept for subagent registry)
# ---------------------------------------------------------------------------

RESEARCH_DESCRIPTION = (
    "Deep research specialist for iterative multi-source research. Generates "
    "search queries, gathers information from web, academic, and other sources, "
    "reflects on knowledge gaps, and synthesises a comprehensive answer with "
    "citations. Use for questions requiring thorough research across multiple sources."
)


# ---------------------------------------------------------------------------
# InquiryEngine-backed factory
# ---------------------------------------------------------------------------


def _build_inquiry_sources(config: Any | None = None) -> list:
    """Create the default source set for web research.

    Returns:
        List of InformationSource instances [WebSource, AcademicSource].
    """
    from soothe.inquiry.sources.academic import AcademicSource
    from soothe.inquiry.sources.web import WebSource

    return [
        WebSource(config=config),
        AcademicSource(),
    ]


def create_research_subagent(
    model: str | BaseChatModel | None = None,
    max_loops: int = 2,
    config: Any | None = None,
    **_kwargs: object,
) -> CompiledSubAgent:
    """Create a Research subagent backed by the InquiryEngine.

    The engine is configured with ``WebSource`` and ``AcademicSource``
    for backward-compatible web research behaviour.  The InquiryEngine
    handles the full iterative loop: analyse -> query -> gather ->
    reflect -> synthesise.

    Args:
        model: LLM model string or ``BaseChatModel`` instance.
        max_loops: Maximum research reflection loops.
        config: Optional Soothe config for tool and source configuration.
        **_kwargs: Additional config (ignored for forward compat).

    Returns:
        ``CompiledSubAgent`` dict compatible with deepagents.
    """
    import os

    from langchain.chat_models import init_chat_model

    from soothe.inquiry.engine import build_inquiry_engine
    from soothe.inquiry.protocol import InquiryConfig

    if model is None:
        msg = (
            "Research subagent requires a model. Pass a model string "
            "(e.g. 'openai:qwen3.5-flash') or a BaseChatModel instance."
        )
        raise ValueError(msg)

    if isinstance(model, str):
        # If we have a SootheConfig and the model string contains a custom provider name,
        # use create_chat_model to properly resolve it
        if config and hasattr(config, "providers") and ":" in model:
            provider_name = model.split(":", 1)[0]
            # Check if this provider is defined in the config
            provider_names = [p.name for p in config.providers] if config.providers else []
            if provider_name in provider_names:
                # Use SootheConfig's create_chat_model which handles provider:model resolution
                cache_key = model
                if cache_key in config._model_cache:
                    resolved_model = config._model_cache[cache_key]
                else:
                    # Parse provider:model and resolve using SootheConfig logic
                    _, _, model_name = model.partition(":")
                    provider_type, kwargs = config._provider_kwargs(provider_name)
                    init_str = f"{provider_type}:{model_name}" if provider_name else model
                    resolved_model = init_chat_model(init_str, **kwargs)
                    config._model_cache[cache_key] = resolved_model
            else:
                # Standard langchain provider, use init_chat_model directly
                model_kwargs: dict[str, Any] = {}
                base_url = os.environ.get("OPENAI_BASE_URL")
                if base_url:
                    model_kwargs["base_url"] = base_url
                    model_kwargs["use_responses_api"] = False
                resolved_model = init_chat_model(model, **model_kwargs)
        else:
            # Standard provider:model format or plain model name
            model_kwargs: dict[str, Any] = {}
            base_url = os.environ.get("OPENAI_BASE_URL")
            if base_url:
                model_kwargs["base_url"] = base_url
                model_kwargs["use_responses_api"] = False
            resolved_model = init_chat_model(model, **model_kwargs)
    else:
        resolved_model = model

    sources = _build_inquiry_sources(config)
    inquiry_config = InquiryConfig(
        max_loops=max_loops,
        max_sources_per_query=2,
        enabled_sources=["web", "academic"],
    )

    runnable = build_inquiry_engine(
        resolved_model,
        sources,
        inquiry_config,
        _domain="web",
    )

    return {
        "name": "research",
        "description": RESEARCH_DESCRIPTION,
        "runnable": runnable,
    }
