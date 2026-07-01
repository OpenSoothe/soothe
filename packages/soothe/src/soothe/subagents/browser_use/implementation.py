"""BrowserUse subagent -- web browser automation specialist.

Provides web browser automation for navigating pages, interacting with
elements, filling forms, extracting content, and taking screenshots.

Uses only soothe-sdk (no soothe daemon dependency).
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from soothe_sdk.core.subagent_wire import emit_subagent_wire_event
from soothe_sdk.utils.formatting import format_cli_error

from soothe.subagents.browser_use._preview import preview_first
from soothe.subagents.browser_use._runtime import (
    cleanup_browser_temp_files,
    cleanup_stale_chrome,
    get_browser_extensions_dir,
    get_browser_runtime_dir,
    get_browser_user_data_dir,
)
from soothe.subagents.browser_use.config_model import BrowserUseSubagentConfig
from soothe.subagents.browser_use.display_summary import browser_use_result_summary_for_display
from soothe.subagents.browser_use.events import (
    BrowserUseCompletedEvent,
    BrowserUseStartedEvent,
    BrowserUseStepCompletedEvent,
)

logger = logging.getLogger(__name__)


async def detect_existing_browser_intent(
    prompt: str,
    config: Any | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> bool:
    """Use LLM to detect if user wants to use existing browser instance.

    Args:
        prompt: User's task prompt.
        config: Optional configuration object with ``create_chat_model`` (e.g. Soothe).
        model_name: Model name for intent detection (fallback if no config).
        base_url: Base URL for the LLM API (fallback if no config).
        api_key: API key for the LLM (fallback if no config).

    Returns:
        True if user wants existing browser, False otherwise.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

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
        # Use config if available (applies OpenAI-compat wrappers for custom endpoints)
        if config:
            model = config.create_chat_model("fast")
        else:
            from langchain.chat_models import init_chat_model

            logger.warning("No config provided, OpenAI compatibility wrapper NOT applied")
            model = init_chat_model(
                model=model_name or "gpt-4o-mini",
                model_provider="openai",
                base_url=base_url,
                api_key=api_key,
                temperature=0.0,
            )

        messages = [
            SystemMessage(content=detection_prompt),
            HumanMessage(content=prompt),
        ]
        # Metadata for tracing (optional soothe middleware)
        metadata: dict[str, Any] = {}
        try:
            from soothe.middleware._utils import create_llm_call_metadata

            metadata = create_llm_call_metadata(
                purpose="intent_detection",
                component="soothe.subagents.browser_use",
                phase="initialization",
                existing_browser_check=True,
            )
        except ImportError:
            pass

        from soothe.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )

        async def _invoke() -> Any:
            return await model.ainvoke(
                messages,
                config={"metadata": metadata},
            )

        response = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(config),
        )
        content = response.content.strip()
        result: bool = content.lower() == "yes"
    except Exception as e:
        logger.warning("LLM intent detection failed: %s", e)
        return False  # Fallback to new instance
    else:
        logger.info("Intent detection for '%s...': %s", preview_first(prompt, 50), result)
        return result


BROWSER_DESCRIPTION = (
    "Browser automation specialist for WEB tasks ONLY. "
    "Can navigate pages, click elements, fill forms, extract content, and take screenshots. "
    "Use ONLY for: web URLs (http/https), web scraping, form automation, browser-based testing. "
    "DO NOT use for: local files (pwd, ls, cat), directory listing, file reading, local commands. "
    "For local files, use: list_files, read_file, run_command tools instead."
)


class _BrowserUseState(TypedDict):
    """State schema for the browser_use subagent graph."""

    messages: Annotated[list[Any], add_messages]


def _suppress_external_browser_loggers() -> None:
    """Mute noisy third-party browser-use loggers."""
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


class _SuppressOutput:
    """Simple context manager to suppress stdout during browser operations."""

    def __enter__(self) -> _SuppressOutput:
        self._original_stdout = os.dup(1)
        self._devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(self._devnull, 1)
        return self

    def __exit__(self, *args: Any) -> None:
        os.dup2(self._original_stdout, 1)
        os.close(self._devnull)
        os.close(self._original_stdout)


def _build_browser_use_graph(
    *,
    headless: bool = True,
    max_steps: int | None = None,
    use_vision: bool = True,
    browser_model: str | None = None,
    browser_base_url: str | None = None,
    browser_api_key: str | None = None,
    config: BrowserUseSubagentConfig | None = None,
) -> Any:
    """Build and compile the browser_use LangGraph.

    Args:
        headless: Run browser in headless mode.
        max_steps: Maximum steps for the browser agent. When ``None``, uses
            ``BrowserUseSubagentConfig.max_steps`` (default 10).
        use_vision: Enable vision/screenshot support.
        browser_model: Model name for browser-use LLM (e.g. `qwen3.5-flash`).
        browser_base_url: Base URL for the browser-use LLM.
        browser_api_key: API key for the browser-use LLM.
        config: BrowserUse subagent configuration object.

    Returns:
        Compiled LangGraph runnable.
    """
    browser_config = config or BrowserUseSubagentConfig()
    resolved_max_steps = max_steps if max_steps is not None else browser_config.max_steps

    async def _run_browser_use_async(state: _BrowserUseState | dict[str, Any]) -> dict[str, Any]:
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

        # Configure browser runtime directories (using local implementations)
        import uuid

        browser_runtime_dir = browser_config.runtime_dir or str(get_browser_runtime_dir())
        browser_extensions_dir = browser_config.extensions_dir or str(get_browser_extensions_dir())

        ephemeral_profile_dir: str | None = None
        if browser_config.user_data_dir:
            browser_user_data_dir = browser_config.user_data_dir
        elif browser_config.profile_mode == "ephemeral":
            profile_name = f"session-{uuid.uuid4().hex[:12]}"
            browser_user_data_dir = str(get_browser_user_data_dir(profile_name))
            ephemeral_profile_dir = browser_user_data_dir
            logger.info("Using ephemeral browser profile: %s", profile_name)
        else:
            browser_user_data_dir = str(get_browser_user_data_dir())

        # Set environment variables for browser-use
        os.environ["BROWSER_USE_CONFIG_DIR"] = browser_runtime_dir
        os.environ["BROWSER_USE_PROFILES_DIR"] = browser_user_data_dir
        os.environ["BROWSER_USE_EXTENSIONS_DIR"] = browser_extensions_dir

        _suppress_external_browser_loggers()

        # Use simple output suppression context manager
        output_suppressor = _SuppressOutput()

        run_t0 = time.perf_counter()
        result = "BrowserUse task completed (no extracted content.)"

        try:
            with output_suppressor:
                from browser_use import Agent as BrowserAgent
                from browser_use import Browser

                messages = state.get("messages", [])
                task = messages[-1].content if messages else ""

                emit_subagent_wire_event(
                    BrowserUseStartedEvent(task_preview=preview_first(str(task), 200)).to_dict(),
                    logger,
                )

                model_name = browser_model or "qwen3.5-flash"
                if ":" in model_name:
                    model_name = model_name.split(":", 1)[1]

                logger.info(
                    "BrowserUse subagent: starting run task_len=%d chars headless=%s max_steps=%d "
                    "use_vision=%s browser_use_model=%s",
                    len(task) if isinstance(task, str) else 0,
                    headless,
                    resolved_max_steps,
                    use_vision,
                    model_name,
                )
                logger.info("BrowserUse subagent: task preview: %s", preview_first(str(task), 400))

                # Configure LLM
                llm_kwargs: dict[str, Any] = {"model": model_name}
                if browser_base_url:
                    llm_kwargs["base_url"] = browser_base_url
                if browser_api_key:
                    llm_kwargs["api_key"] = browser_api_key

                from browser_use.llm import ChatOpenAI as BrowserChatOpenAI

                llm = BrowserChatOpenAI(**llm_kwargs)

                cdp_url = None
                if browser_config.enable_existing_browser:
                    use_existing = await detect_existing_browser_intent(
                        task,
                        model_name=model_name,
                        base_url=browser_base_url,
                        api_key=browser_api_key,
                    )
                    if use_existing:
                        # Try to find existing browser via CDP (simplified)
                        cdp_url = os.environ.get("CHROME_CDP_URL")
                        if cdp_url:
                            logger.info("Using existing browser at %s", cdp_url)
                        else:
                            logger.info("No existing browser CDP URL found, launching new instance")

                if not cdp_url:
                    killed = cleanup_stale_chrome(browser_user_data_dir)
                    if killed:
                        import asyncio

                        logger.info("Cleaned up %d stale Chrome process(es)", killed)
                        await asyncio.sleep(1)

                extra_args = [f"--user-data-dir={browser_user_data_dir}"]
                browser_instance = Browser(
                    headless=headless if not cdp_url else False,
                    cdp_url=cdp_url,
                    args=extra_args,
                    user_data_dir=browser_user_data_dir,
                )
                logger.info(
                    "BrowserUse subagent: Browser() ready cdp_url=%r headless_effective=%s user_data_dir=%s",
                    cdp_url,
                    headless if not cdp_url else False,
                    preview_first(str(browser_user_data_dir), 120),
                )

                last_step_wall = time.perf_counter()

                async def on_step_end(agent: Any) -> None:
                    nonlocal last_step_wall
                    step_num = agent.state.n_steps
                    last = agent.history.history[-1] if agent.history.history else None
                    action_desc = ""
                    page_title = ""
                    url = None
                    if last:
                        if hasattr(last, "model_output") and last.model_output:
                            action = getattr(last.model_output, "action", None)
                            if action:
                                action_desc = preview_first(str(action), 80)
                        if hasattr(last, "state"):
                            url = getattr(last.state, "url", None)
                            page_title = preview_first(getattr(last.state, "title", ""), 60)
                    now = time.perf_counter()
                    wall_since_prev = now - last_step_wall
                    last_step_wall = now
                    logger.info(
                        "BrowserUse subagent step: n_steps=%s wall_since_prev=%.2fs "
                        "since_run_start=%.1fs url=%r title=%r action=%r is_done=%s "
                        "history_len=%d",
                        step_num,
                        wall_since_prev,
                        now - run_t0,
                        url or "",
                        page_title,
                        action_desc or "(none)",
                        agent.history.is_done(),
                        len(agent.history.history) if agent.history.history else 0,
                    )
                    emit_subagent_wire_event(
                        BrowserUseStepCompletedEvent(
                            step_index=int(step_num),
                            url=str(url or ""),
                            title=str(page_title),
                            action_preview=str(action_desc or "")[:120],
                            status="done" if agent.history.is_done() else "running",
                        ).to_dict(),
                        logger,
                    )

                agent = BrowserAgent(
                    task=task,
                    llm=llm,
                    browser=browser_instance,
                    use_vision=use_vision,
                )

                # Start the browser session
                logger.info("BrowserUse subagent: calling browser_session.start()")
                sess_t0 = time.perf_counter()
                await agent.browser_session.start()
                logger.info(
                    "BrowserUse subagent: browser_session.start() finished in %.2fs",
                    time.perf_counter() - sess_t0,
                )

                # Run step-by-step to emit progress events
                for step_idx in range(resolved_max_steps):
                    try:
                        iter_t0 = time.perf_counter()
                        logger.info(
                            "BrowserUse subagent: invoking agent.step() (%d/%d, elapsed=%.1fs)",
                            step_idx + 1,
                            resolved_max_steps,
                            iter_t0 - run_t0,
                        )
                        await agent.step()
                        logger.info(
                            "BrowserUse subagent: agent.step() returned in %.2fs",
                            time.perf_counter() - iter_t0,
                        )
                        await on_step_end(agent)
                        if agent.history.is_done():
                            logger.info(
                                "BrowserUse subagent: agent reports is_done=True after %d step(s)",
                                step_idx + 1,
                            )
                            break
                    except Exception:
                        logger.exception("BrowserUse step failed")
                        raise

                history = agent.history
                result = (
                    history.final_result() or "BrowserUse task completed (no extracted content.)"
                )
                result_str = str(result)
                completion_summary = browser_use_result_summary_for_display(result_str)
                logger.info(
                    "BrowserUse subagent: loop finished total_wall=%.1fs steps_executed=%d result_preview=%s",
                    time.perf_counter() - run_t0,
                    len(history.history) if history.history else 0,
                    preview_first(result_str, 300),
                )

                emit_subagent_wire_event(
                    BrowserUseCompletedEvent(
                        duration_ms=int((time.perf_counter() - run_t0) * 1000),
                        success=True,
                        summary=completion_summary,
                    ).to_dict(),
                    logger,
                )

                # Stop the browser session
                try:
                    logger.info("BrowserUse subagent: stopping browser_session")
                    await agent.browser_session.stop()
                except Exception:
                    logger.info("Failed to stop browser session (already stopped?)")

                if browser_config.cleanup_on_exit:
                    cleanup_browser_temp_files()

        except Exception as e:
            logger.exception("BrowserUse agent failed")
            error_msg = format_cli_error(e)
            result = error_msg

            emit_subagent_wire_event(
                BrowserUseCompletedEvent(
                    duration_ms=int((time.perf_counter() - run_t0) * 1000),
                    success=False,
                    summary=browser_use_result_summary_for_display(error_msg),
                ).to_dict(),
                logger,
            )
        finally:
            if ephemeral_profile_dir:
                import shutil

                shutil.rmtree(ephemeral_profile_dir, ignore_errors=True)
                logger.info("Cleaned up ephemeral profile: %s", ephemeral_profile_dir)

        return {"messages": [AIMessage(content=result)]}

    async def run_browser_use(state: _BrowserUseState) -> dict[str, Any]:
        """Async browser_use function for LangGraph."""
        return await _run_browser_use_async(state)

    graph = StateGraph(_BrowserUseState)
    graph.add_node("run_browser_use", run_browser_use)
    graph.add_edge(START, "run_browser_use")
    graph.add_edge("run_browser_use", END)
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


def _create_browser_use_subagent(
    model: Any = None,
    *,
    headless: bool = True,
    max_steps: int | None = None,
    use_vision: bool = True,
    config: BrowserUseSubagentConfig | None = None,
    **kwargs: Any,
) -> CompiledSubAgent:
    """Create a BrowserUse subagent (CompiledSubAgent with browser-use workflow).

    Args:
        model: Model name string or langchain BaseChatModel for the browser-use
            LLM. If a BaseChatModel instance is passed, the model name is
            extracted automatically.
        headless: Run browser in headless mode.
        max_steps: Maximum browser agent steps. When ``None``, uses
            ``BrowserUseSubagentConfig.max_steps`` (default 10).
        use_vision: Enable vision/screenshot support.
        config: BrowserUse subagent configuration object with runtime directories,
            cleanup settings, and feature flags.
        **kwargs: Additional config -- `base_url` and `api_key` are forwarded
            to the browser-use LLM.

    Returns:
        `CompiledSubAgent` dict compatible with deepagents.
    """
    model_name = _extract_model_name(model)

    # Get base_url and api_key from kwargs or fall back to environment
    browser_base_url = kwargs.get("base_url") or os.environ.get("OPENAI_BASE_URL")
    browser_api_key = kwargs.get("api_key") or os.environ.get("OPENAI_API_KEY")

    runnable = _build_browser_use_graph(
        headless=headless,
        max_steps=max_steps,
        use_vision=use_vision,
        browser_model=model_name,
        browser_base_url=browser_base_url,
        browser_api_key=browser_api_key,
        config=config,
    )

    return {
        "name": "browser_use",
        "description": BROWSER_DESCRIPTION,
        "runnable": runnable,
    }
