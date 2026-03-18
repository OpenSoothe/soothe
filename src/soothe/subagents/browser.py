"""Browser subagent -- web browser automation specialist.

Provides web browser automation for navigating pages, interacting with
elements, filling forms, extracting content, and taking screenshots.

Requires the optional `browser` extra: `pip install soothe[browser]`
"""

from __future__ import annotations

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


async def detect_existing_browser_intent(prompt: str, model: Any) -> bool:
    """Use LLM to detect if user wants to use existing browser instance.

    Args:
        prompt: User's task prompt.
        model: Language model for intent detection.

    Returns:
        True if user wants existing browser, False otherwise.
    """
    detection_prompt = f"""Analyze this user request and determine if the user wants to use an \
existing browser instance (e.g., one they've already opened and logged into).

User request: "{prompt}"

Respond with only "yes" or "no".

Examples:
- "Use my existing browser to check Gmail" → yes
- "Browse to example.com" → no
- "Check my logged-in GitHub account" → yes
- "Search for Python tutorials" → no
- "Use the Chrome I already have open where I'm logged in" → yes
- "Navigate to my company portal using my current session" → yes"""

    try:
        # browser-use ChatOpenAI expects browser_use.llm.messages.UserMessage
        from browser_use.llm.messages import UserMessage

        response = await model.ainvoke([UserMessage(content=detection_prompt)])
        content = response.content.strip()
        result = content.lower() == "yes"
    except Exception as e:
        logger.warning("LLM intent detection failed: %s", e)
        return False  # Fallback to new instance
    else:
        logger.debug("Intent detection for '%s...': %s", prompt[:50], result)
        return result


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

        # Increase browser-use event timeouts for slower systems / first launch.
        start_timeout = str(browser_config.browser_start_timeout)
        os.environ.setdefault("TIMEOUT_BrowserStartEvent", start_timeout)
        os.environ.setdefault("TIMEOUT_BrowserLaunchEvent", start_timeout)

        # Configure browser runtime directories
        import uuid

        from soothe.utils.runtime import (
            get_browser_downloads_dir,
            get_browser_extensions_dir,
            get_browser_runtime_dir,
            get_browser_user_data_dir,
        )

        browser_runtime_dir = browser_config.runtime_dir or str(get_browser_runtime_dir())
        browser_downloads_dir = browser_config.downloads_dir or str(get_browser_downloads_dir())
        browser_extensions_dir = browser_config.extensions_dir or str(get_browser_extensions_dir())

        ephemeral_profile_dir: str | None = None
        if browser_config.user_data_dir:
            browser_user_data_dir = browser_config.user_data_dir
        elif browser_config.profile_mode == "ephemeral":
            profile_name = f"session-{uuid.uuid4().hex[:12]}"
            browser_user_data_dir = str(get_browser_user_data_dir(profile_name))
            ephemeral_profile_dir = browser_user_data_dir
            logger.debug("Using ephemeral browser profile: %s", profile_name)
        else:
            browser_user_data_dir = str(get_browser_user_data_dir())

        # Set environment variables for browser-use
        os.environ["BROWSER_USE_CONFIG_DIR"] = browser_runtime_dir
        os.environ["BROWSER_USE_PROFILES_DIR"] = browser_user_data_dir
        os.environ["BROWSER_USE_EXTENSIONS_DIR"] = browser_extensions_dir

        _suppress_external_browser_loggers()

        from soothe.utils.output_capture import capture_subagent_output
        from soothe.utils.progress import emit_progress as _emit

        try:
            # Capture browser-use stdout/stderr output (Crawl4AI init, browser startup, etc.)
            with capture_subagent_output("browser", suppress=True):
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

                # Detect if user wants to use existing browser
                cdp_url = None
                use_existing = False
                if browser_config.enable_existing_browser:
                    use_existing = await detect_existing_browser_intent(task, llm)
                    if use_existing:
                        from soothe.utils.browser_cdp import find_available_cdp

                        cdp_url = await find_available_cdp()
                        if cdp_url:
                            logger.info("Connecting to existing browser at %s", cdp_url)
                            _emit(
                                {
                                    "type": "soothe.browser.cdp",
                                    "status": "connected",
                                    "cdp_url": cdp_url,
                                },
                                logger,
                            )
                        else:
                            logger.info("Existing browser requested but none found, launching new instance")
                            _emit(
                                {
                                    "type": "soothe.browser.cdp",
                                    "status": "not_found",
                                    "message": "Existing browser requested but none found",
                                },
                                logger,
                            )

                if not cdp_url:
                    from soothe.utils.browser_cdp import cleanup_stale_chrome

                    killed = cleanup_stale_chrome(browser_user_data_dir)
                    if killed:
                        import asyncio

                        logger.info(
                            "Cleaned up %d stale Chrome process(es) using %s",
                            killed,
                            browser_user_data_dir,
                        )
                        await asyncio.sleep(1)

                browser = BrowserSession(
                    headless=headless if not cdp_url else False,
                    downloads_path=browser_downloads_dir,
                    user_data_dir=browser_user_data_dir,
                    cdp_url=cdp_url,
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
            from soothe.utils.error_format import format_cli_error

            error_msg = format_cli_error(e, context="Browser agent")
            result = error_msg
        finally:
            if ephemeral_profile_dir:
                import shutil

                shutil.rmtree(ephemeral_profile_dir, ignore_errors=True)
                logger.debug("Cleaned up ephemeral profile: %s", ephemeral_profile_dir)

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
