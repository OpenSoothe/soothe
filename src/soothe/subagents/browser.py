"""Browser subagent -- wraps the browser-use library as a CompiledSubAgent.

Provides web browser automation via the browser-use Agent, which manages its own
LLM calls, browser lifecycle, and action loop internally.

Requires the optional `browser` extra: `pip install soothe[browser]`
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)

BROWSER_DESCRIPTION = (
    "Browser automation agent for web tasks. Can navigate pages, click elements, "
    "fill forms, extract content, and take screenshots. Powered by the browser-use "
    "library with its own LLM loop. Use for web scraping, form automation, and "
    "browser-based testing. Requires the 'browser' extra."
)


class _BrowserState(dict):
    """State schema for the browser subagent graph."""

    messages: Annotated[list, add_messages]


def _build_browser_graph(
    *,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    browser_model: str | None = None,
    browser_base_url: str | None = None,
    browser_api_key: str | None = None,
    disable_extensions: bool = True,
    disable_cloud: bool = True,
    disable_telemetry: bool = True,
) -> Any:
    """Build and compile the browser LangGraph.

    Args:
        headless: Run browser in headless mode.
        max_steps: Maximum steps for the browser agent.
        use_vision: Enable vision/screenshot support.
        browser_model: Model name for browser-use LLM (e.g. `qwen3.5-flash`).
        browser_base_url: Base URL for the browser-use LLM.
        browser_api_key: API key for the browser-use LLM.
        disable_extensions: Disable browser extensions (uBlock Origin, cookie handler, ClearURLs).
        disable_cloud: Disable browser-use cloud service connections.
        disable_telemetry: Disable anonymous usage telemetry.

    Returns:
        Compiled LangGraph runnable.
    """

    async def _run_browser_async(state: dict[str, Any]) -> dict[str, Any]:
        import os

        # Disable browser-use privacy-invasive features before importing
        if disable_extensions:
            os.environ["BROWSER_USE_DISABLE_EXTENSIONS"] = "1"

        if disable_cloud:
            os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
            os.environ.pop("BROWSER_USE_API_KEY", None)

        if disable_telemetry:
            os.environ["ANONYMIZED_TELEMETRY"] = "false"

        # Now import browser-use (will read env vars during initialization)
        from browser_use import Agent as BrowserAgent, BrowserSession
        from browser_use.llm.openai.chat import ChatOpenAI as BUChatOpenAI

        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
        except (ImportError, RuntimeError):
            writer = None

        def emit_progress(event: dict[str, Any]) -> None:
            if writer:
                writer(event)
            logger.info("Browser progress: %s", event)

        messages = state.get("messages", [])
        task = messages[-1].content if messages else ""

        # Strip provider prefix if present (e.g., "openai:qwen3.5-flash" -> "qwen3.5-flash")
        model_name = browser_model or "qwen3.5-flash"
        if ":" in model_name:
            model_name = model_name.split(":", 1)[1]

        # browser-use's ChatOpenAI expects model as first positional parameter
        llm_kwargs: dict[str, Any] = {}
        if browser_base_url:
            llm_kwargs["base_url"] = browser_base_url
        if browser_api_key:
            llm_kwargs["api_key"] = browser_api_key
        llm = BUChatOpenAI(model_name, **llm_kwargs)

        browser = BrowserSession(headless=headless)

        async def on_step_end(agent: Any) -> None:
            step_num = agent.state.n_steps
            last = agent.history.history[-1] if agent.history.history else None
            emit_progress(
                {
                    "type": "browser_step",
                    "step": step_num,
                    "url": last.state.url if last and hasattr(last, "state") else None,
                    "is_done": agent.history.is_done(),
                }
            )

        agent = BrowserAgent(
            task=task,
            llm=llm,
            browser=browser,
            use_vision=use_vision,
        )

        try:
            history = await agent.run(max_steps=max_steps, on_step_end=on_step_end)
            result = history.final_result() or "Browser task completed (no extracted content)."
        except Exception:
            logger.exception("Browser agent failed")
            result = "Browser agent encountered an error."

        return {"messages": [AIMessage(content=result)]}

    def run_browser(state: dict[str, Any]) -> dict[str, Any]:
        """Synchronous wrapper for the async browser function."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # If we're already in an async context, create a new loop
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(_run_browser_async(state))
            finally:
                new_loop.close()
        else:
            return loop.run_until_complete(_run_browser_async(state))

    graph = StateGraph(_BrowserState)
    graph.add_node("run_browser", run_browser)
    graph.add_edge(START, "run_browser")
    graph.add_edge("run_browser", END)
    return graph.compile()


def _extract_model_name(model: Any) -> str | None:
    """Extract a plain model name string from various model representations.

    browser-use creates its own LLM internally; it needs a model name string,
    not a langchain BaseChatModel instance.
    """
    if model is None:
        return None
    if isinstance(model, str):
        return model
    for attr in ("model_name", "model"):
        val = getattr(model, attr, None)
        if isinstance(val, str):
            return val
    return None


def create_browser_subagent(
    model: Any = None,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    disable_extensions: bool = True,
    disable_cloud: bool = True,
    disable_telemetry: bool = True,
    **kwargs: Any,
) -> CompiledSubAgent:
    """Create a Browser subagent (CompiledSubAgent with browser-use workflow).

    Args:
        model: Model name string or langchain BaseChatModel for the browser-use
            LLM. If a BaseChatModel instance is passed, the model name is
            extracted automatically.
        headless: Run browser in headless mode.
        max_steps: Maximum browser agent steps.
        use_vision: Enable vision/screenshot support.
        disable_extensions: Disable browser extensions (uBlock Origin, cookie handler, ClearURLs).
            Privacy-invasive extensions are disabled by default. Set to False to enable them.
        disable_cloud: Disable browser-use cloud service connections.
            Cloud features are disabled by default. Set to False to enable cloud sync.
        disable_telemetry: Disable anonymous usage telemetry.
            Telemetry is disabled by default. Set to False to enable anonymous usage data collection.
        **kwargs: Additional config -- `base_url` and `api_key` are forwarded
            to the browser-use LLM.

    Returns:
        `CompiledSubAgent` dict compatible with deepagents.
    """
    import os

    model_name = _extract_model_name(model)

    # Get base_url and api_key from kwargs or fall back to environment
    browser_base_url = kwargs.get("base_url") or os.environ.get("OPENAI_BASE_URL")
    browser_api_key = kwargs.get("api_key") or os.environ.get("OPENAI_API_KEY")

    runnable = _build_browser_graph(
        headless=headless,
        max_steps=max_steps,
        use_vision=use_vision,
        browser_model=model_name,
        browser_base_url=browser_base_url,
        browser_api_key=browser_api_key,
        disable_extensions=disable_extensions,
        disable_cloud=disable_cloud,
        disable_telemetry=disable_telemetry,
    )

    return {
        "name": "browser",
        "description": BROWSER_DESCRIPTION,
        "runnable": runnable,
    }
