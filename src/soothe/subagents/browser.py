"""Browser subagent -- web browser automation specialist.

Provides web browser automation for navigating pages, interacting with
elements, filling forms, extracting content, and taking screenshots.

Requires the optional `browser` extra: `pip install soothe[browser]`
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from soothe.config import BrowserSubagentConfig

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent

logger = logging.getLogger(__name__)

BROWSER_DESCRIPTION = (
    "Browser automation specialist for web tasks. Can navigate pages, click "
    "elements, fill forms, extract content, and take screenshots. Use for "
    "web scraping, form automation, and browser-based testing."
)


class _BrowserState(dict):
    """State schema for the browser subagent graph."""

    messages: Annotated[list, add_messages]


def _suppress_external_browser_loggers() -> None:
    """Mute noisy third-party browser-use loggers in Soothe surfaces."""
    noisy_loggers = (
        "browser_use",
        "bubus",
        "cdp_use",
        "Agent",
        "BrowserSession",
        "tools",
    )
    for name in noisy_loggers:
        ext_logger = logging.getLogger(name)
        ext_logger.setLevel(logging.CRITICAL)
        ext_logger.propagate = False


def _build_browser_graph(
    *,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    browser_model: str | None = None,
    browser_base_url: str | None = None,
    browser_api_key: str | None = None,
    config: BrowserSubagentConfig | None = None,
) -> Any:
    """Build and compile the browser LangGraph.

    Args:
        headless: Run browser in headless mode.
        max_steps: Maximum steps for the browser agent.
        use_vision: Enable vision/screenshot support.
        browser_model: Model name for browser-use LLM (e.g. `qwen3.5-flash`).
        browser_base_url: Base URL for the browser-use LLM.
        browser_api_key: API key for the browser-use LLM.
        config: Browser subagent configuration object.

    Returns:
        Compiled LangGraph runnable.
    """
    # Use provided config or create default
    browser_config = config or BrowserSubagentConfig()

    async def _run_browser_async(state: dict[str, Any]) -> dict[str, Any]:
        # Disable browser-use privacy-invasive features before importing
        if browser_config.disable_extensions:
            os.environ["BROWSER_USE_DISABLE_EXTENSIONS"] = "1"

        if browser_config.disable_cloud:
            os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
            os.environ.pop("BROWSER_USE_API_KEY", None)

        if browser_config.disable_telemetry:
            os.environ["ANONYMIZED_TELEMETRY"] = "false"

        # Ask browser-use to avoid chatty console logging where supported.
        os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "result")

        # Configure browser runtime directories
        from soothe.utils.runtime import (
            get_browser_downloads_dir,
            get_browser_extensions_dir,
            get_browser_runtime_dir,
            get_browser_user_data_dir,
        )

        browser_runtime_dir = browser_config.runtime_dir or str(get_browser_runtime_dir())
        browser_downloads_dir = browser_config.downloads_dir or str(get_browser_downloads_dir())
        browser_user_data_dir = browser_config.user_data_dir or str(get_browser_user_data_dir())
        browser_extensions_dir = browser_config.extensions_dir or str(get_browser_extensions_dir())

        # Set environment variables for browser-use
        os.environ["BROWSER_USE_CONFIG_DIR"] = browser_runtime_dir
        os.environ["BROWSER_USE_PROFILES_DIR"] = browser_user_data_dir
        os.environ["BROWSER_USE_EXTENSIONS_DIR"] = browser_extensions_dir

        _suppress_external_browser_loggers()

        from soothe.utils.progress import emit_progress as _emit

        try:
            # Suppress browser-use stdout/stderr noise and rely on structured events.
            # Use synchronous file object since contextlib.redirect_stdout/stderr
            # require synchronous context managers
            with open(os.devnull, "w", encoding="utf-8") as devnull_file:
                with (
                    contextlib.redirect_stdout(devnull_file),
                    contextlib.redirect_stderr(devnull_file),
                ):
                    # Import browser-use under redirected stdio so startup logs are hidden.
                    from browser_use import Agent as BrowserAgent, BrowserSession
                    from browser_use.llm.openai.chat import ChatOpenAI as BUChatOpenAI

                    messages = state.get("messages", [])
                    task = messages[-1].content if messages else ""

                    # Strip provider prefix if present (e.g., "openai:qwen3.5-flash" -> "qwen3.5-flash")
                    model_name = browser_model or "qwen3.5-flash"
                    if ":" in model_name:
                        model_name = model_name.split(":", 1)[1]

                    llm_kwargs: dict[str, Any] = {}
                    if browser_base_url:
                        llm_kwargs["base_url"] = browser_base_url
                    if browser_api_key:
                        llm_kwargs["api_key"] = browser_api_key
                    llm = BUChatOpenAI(model_name, **llm_kwargs)

                    browser = BrowserSession(
                        headless=headless,
                        downloads_path=browser_downloads_dir,
                        user_data_dir=browser_user_data_dir,
                    )

                    async def on_step_end(agent: Any) -> None:
                        step_num = agent.state.n_steps
                        last = agent.history.history[-1] if agent.history.history else None
                        action_desc = ""
                        page_title = ""
                        url = None
                        if last:
                            if hasattr(last, "model_output") and last.model_output:
                                action = getattr(last.model_output, "action", None)
                                if action:
                                    action_desc = str(action)[:80]
                            if hasattr(last, "state"):
                                url = getattr(last.state, "url", None)
                                page_title = getattr(last.state, "title", "")[:60]
                        _emit(
                            {
                                "type": "soothe.browser.step",
                                "step": step_num,
                                "url": url,
                                "action": action_desc,
                                "title": page_title,
                                "is_done": agent.history.is_done(),
                            },
                            logger,
                        )

                    agent = BrowserAgent(
                        task=task,
                        llm=llm,
                        browser=browser,
                        use_vision=use_vision,
                    )
                    history = await agent.run(max_steps=max_steps, on_step_end=on_step_end)
                    result = history.final_result() or "Browser task completed (no extracted content)."

                    # Clean up temporary files if requested
                    if browser_config.cleanup_on_exit:
                        from soothe.utils.runtime import cleanup_browser_temp_files

                        cleanup_browser_temp_files()
        except Exception as e:
            logger.exception("Browser agent failed")
            error_type = type(e).__name__
            error_msg = str(e)
            result = f"Browser agent encountered an error: {error_type}: {error_msg}"

        return {"messages": [AIMessage(content=result)]}

    async def run_browser(state: dict[str, Any]) -> dict[str, Any]:
        """Async browser function for LangGraph."""
        return await _run_browser_async(state)

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
    *,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    config: BrowserSubagentConfig | None = None,
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
        config: Browser subagent configuration object with runtime directories,
            cleanup settings, and feature flags.
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
        config=config,
    )

    return {
        "name": "browser",
        "description": BROWSER_DESCRIPTION,
        "runnable": runnable,
    }
