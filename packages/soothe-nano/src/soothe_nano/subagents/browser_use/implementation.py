"""BrowserUse subagent -- web browser automation specialist.

Provides web browser automation for navigating pages, interacting with
elements, filling forms, extracting content, and taking screenshots.

Uses only soothe-sdk (no soothe daemon dependency).
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

if TYPE_CHECKING:
    from soothe_deepagents.middleware.subagents import CompiledSubAgent

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from soothe_sdk.utils.formatting import format_cli_error

from soothe_nano.subagents.browser_use._preview import preview_first
from soothe_nano.subagents.browser_use._runtime import (
    cleanup_browser_temp_files,
    cleanup_stale_chrome,
    get_browser_extensions_dir,
    get_browser_runtime_dir,
    get_browser_user_data_dir,
)
from soothe_nano.subagents.browser_use.action_format import summarize_browser_step_action
from soothe_nano.subagents.browser_use.config_model import BrowserUseSubagentConfig
from soothe_nano.subagents.browser_use.display_summary import browser_use_result_summary_for_display
from soothe_nano.subagents.browser_use.events import (
    BrowserUseCompletedEvent,
    BrowserUseStartedEvent,
    BrowserUseStepCompletedEvent,
)
from soothe_nano.utils.subagent_emit import emit_subagent_wire_event

logger = logging.getLogger(__name__)

_NO_EXTRACTED_CONTENT = "BrowserUse task completed (no extracted content.)"
_MAX_HISTORY_DIGEST_STEPS = 12


class _BrowserUseSynthesisDecision(BaseModel):
    """Structured result-quality judgement and fallback answer synthesis."""

    use_raw_result: bool = Field(
        default=True,
        description="Whether raw browser_use result is already sufficient for end-user answer.",
    )
    answer_quality: Literal["sufficient", "insufficient"] = Field(
        default="insufficient",
        description="Whether the selected answer is sufficient to complete the task.",
    )
    final_answer: str = Field(
        default="",
        description="User-facing final answer text (raw or synthesized).",
    )
    summary: str = Field(
        default="",
        description="Short completion summary for subagent completion card.",
    )
    rationale: str = Field(
        default="",
        description="Brief explanation for the quality judgement and answer choice.",
    )


def _log_browser_event(event: str, **fields: Any) -> None:
    """Emit a compact structured browser-use log line.

    Example:
        browser_use event=run_start run_id=abc123 model=gpt-4.1 headless=True
    """
    parts = [f"browser_use event={event}"]
    for key, value in fields.items():
        parts.append(f"{key}={value!r}")
    logger.info(" ".join(parts))


def _parse_model_spec(spec: str) -> tuple[str, str]:
    """Split ``provider:model`` into components."""
    provider_name, _, model_name = spec.partition(":")
    if not model_name:
        model_name = provider_name
        provider_name = ""
    return provider_name, model_name


def browser_use_model_role(soothe_config: Any) -> str:
    """Return configured router role for browser_use (default ``default``)."""
    subagents = getattr(soothe_config, "subagents", None) or {}
    sub_cfg = subagents.get("browser_use") if hasattr(subagents, "get") else None
    role = getattr(sub_cfg, "model_role", None) if sub_cfg is not None else None
    return role or "default"


def _resolve_browser_llm_credentials(*, soothe_config: Any) -> tuple[str, str | None, str | None]:
    """Resolve browser-use LLM model name and provider endpoint credentials."""
    resolve = getattr(soothe_config, "resolve_model", None)
    if not callable(resolve):
        msg = "browser_use requires SootheConfig with resolve_model()"
        raise ValueError(msg)

    role = browser_use_model_role(soothe_config)
    spec = resolve(role)
    if not isinstance(spec, str) or not spec.strip():
        msg = f"browser_use model_role={role!r} did not resolve to a model spec"
        raise ValueError(msg)

    provider_name, model_name = _parse_model_spec(spec.strip())
    providers = getattr(soothe_config, "providers", None) or []
    from soothe_nano.utils.llm.registry import ProviderRegistry

    registry = ProviderRegistry(providers)
    _, kwargs = registry.get_provider_kwargs(provider_name)
    return model_name, kwargs.get("base_url"), kwargs.get("api_key")


def _browser_history_had_no_progress(history: Any) -> bool:
    """Return True when the browser agent never navigated or acted."""
    entries = getattr(history, "history", None) or []
    if not entries:
        return True
    for entry in entries:
        state = getattr(entry, "state", None)
        if state is not None:
            url = str(getattr(state, "url", "") or "")
            if url and url not in {"about:blank", "chrome://newtab/", ""}:
                return False
        model_output = getattr(entry, "model_output", None)
        if model_output is not None:
            action = getattr(model_output, "action", None)
            if action:
                return False
    return True


def _format_browser_no_progress_error(*, model_name: str, steps: int) -> str:
    return (
        "BrowserUse failed: the browser agent ran "
        f"{steps} step(s) without navigating away from a blank page or "
        "extracting content. "
        f"Model: {model_name}. "
        "Check subagents.browser_use.model_role and provider API credentials."
    )


def _history_digest_for_synthesis(history: Any) -> str:
    """Return a concise, structured browser trajectory summary for synthesis prompts."""
    entries = list(getattr(history, "history", None) or [])
    if not entries:
        return "(no browser step history)"
    lines: list[str] = []
    for idx, entry in enumerate(entries[:_MAX_HISTORY_DIGEST_STEPS], start=1):
        state = getattr(entry, "state", None)
        url = preview_first(str(getattr(state, "url", "") or ""), 140)
        title = preview_first(str(getattr(state, "title", "") or ""), 60)
        tool_name = "Step"
        action_preview = ""
        model_output = getattr(entry, "model_output", None)
        if model_output is not None:
            action = getattr(model_output, "action", None)
            if action is not None:
                tool_name, action_preview = summarize_browser_step_action(action)
        if not action_preview and url:
            action_preview = url
        line = (
            f"{idx}. tool={tool_name}; action={action_preview or '(none)'}; "
            f"url={url or '(none)'}; title={title or '(none)'}"
        )
        lines.append(line)
    if len(entries) > _MAX_HISTORY_DIGEST_STEPS:
        lines.append(f"... ({len(entries) - _MAX_HISTORY_DIGEST_STEPS} more steps)")
    return "\n".join(lines)


def _apply_browser_use_synthesis_decision(
    *,
    raw_result: str,
    decision: _BrowserUseSynthesisDecision | None,
) -> tuple[str, str, bool, bool]:
    """Resolve final answer/summary from structured synthesis decision.

    Returns:
        Tuple of ``(final_answer, summary, used_synthesized_answer, quality_sufficient)``.
    """
    raw = (raw_result or "").strip()
    if decision is None:
        summary = browser_use_result_summary_for_display(raw)
        return raw, summary, False, False

    preferred = raw if decision.use_raw_result else decision.final_answer.strip()
    if not preferred:
        preferred = raw
    if not preferred:
        preferred = _NO_EXTRACTED_CONTENT
    summary = (decision.summary or "").strip() or browser_use_result_summary_for_display(preferred)
    used_synthesized = preferred != raw and bool(preferred.strip())
    quality_sufficient = decision.answer_quality == "sufficient"
    return preferred, summary, used_synthesized, quality_sufficient


async def _synthesize_browser_use_result(
    *,
    task: str,
    raw_result: str,
    history_digest: str,
    soothe_config: Any,
    browser_config: BrowserUseSubagentConfig,
    run_id: str,
) -> _BrowserUseSynthesisDecision | None:
    """Run deep-research-style structured synthesis over browser run output."""
    from soothe_nano.utils.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )
    from soothe_nano.utils.llm.structured import invoke_structured_chat_typed

    role = (browser_config.synthesis_role or "").strip() or browser_use_model_role(soothe_config)
    try:
        synthesis_model = soothe_config.create_chat_model(role)
    except Exception:
        logger.warning(
            "browser_use synthesis role %r unavailable, skipping synthesis",
            role,
            exc_info=True,
        )
        return None

    prompt = (
        "You are a result-quality judge and report synthesizer for browser automation.\n"
        "Given task, raw browser result, and step trajectory, decide whether raw result is"
        " sufficient.\n"
        "If raw result is low-information, synthesize a better final answer strictly from the"
        " provided evidence.\n"
        "Never invent facts not present in the evidence.\n"
        "Respond in the same language as the task.\n\n"
        f"Task:\n{task or '(empty task)'}\n\n"
        f"Raw result:\n{raw_result or '(empty)'}\n\n"
        f"Browser trajectory:\n{history_digest}\n"
    )
    llm_config = llm_rate_limit_config_from(soothe_config).model_copy(
        update={
            "call_timeout_seconds": int(browser_config.synthesis_timeout_sec),
            "call_timeout_max_seconds": int(browser_config.synthesis_timeout_sec),
        }
    )

    async def _invoke() -> _BrowserUseSynthesisDecision:
        return await invoke_structured_chat_typed(
            synthesis_model,
            [{"role": "user", "content": prompt}],
            _BrowserUseSynthesisDecision,
        )

    _log_browser_event("synthesis_begin", run_id=run_id, role=role)
    try:
        decision = await await_with_llm_call_policy(_invoke, config=llm_config)
    except Exception:
        logger.warning("browser_use synthesis failed (run_id=%s)", run_id, exc_info=True)
        return None
    _log_browser_event(
        "synthesis_end",
        run_id=run_id,
        use_raw=decision.use_raw_result,
        quality=decision.answer_quality,
    )
    return decision


async def detect_existing_browser_intent(prompt: str, *, soothe_config: Any) -> bool:
    """Use LLM to detect if user wants to use existing browser instance.

    Args:
        prompt: User's task prompt.
        soothe_config: Soothe configuration for router-backed LLM calls.

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
        role = browser_use_model_role(soothe_config)
        model = soothe_config.create_chat_model(role)

        messages = [
            SystemMessage(content=detection_prompt),
            HumanMessage(content=prompt),
        ]
        metadata: dict[str, Any] = {}
        try:
            from soothe_nano.utils.llm.observability import create_llm_call_metadata

            metadata = create_llm_call_metadata(
                purpose="intent_detection",
                component="soothe_nano.subagents.browser_use",
                phase="initialization",
                existing_browser_check=True,
            )
        except ImportError:
            pass

        from soothe_nano.utils.llm.invoke_policy import (
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
            config=llm_rate_limit_config_from(soothe_config),
        )
        content = response.content.strip()
        result: bool = content.lower() == "yes"
    except Exception as e:
        logger.warning("LLM intent detection failed: %s", e)
        return False
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
    config: BrowserUseSubagentConfig | None = None,
    soothe_config: Any,
) -> Any:
    """Build and compile the browser_use LangGraph.

    Args:
        headless: Run browser in headless mode.
        max_steps: Maximum steps for the browser agent. When ``None``, uses
            ``BrowserUseSubagentConfig.max_steps`` (default 10).
        use_vision: Enable vision/screenshot support.
        config: BrowserUse subagent configuration object.
        soothe_config: SootheConfig for router-backed browser LLM resolution.

    Returns:
        Compiled LangGraph runnable.
    """
    browser_config = config or BrowserUseSubagentConfig()
    resolved_max_steps = max_steps if max_steps is not None else browser_config.max_steps

    async def _run_browser_use_async(state: _BrowserUseState | dict[str, Any]) -> dict[str, Any]:
        if browser_config.disable_extensions:
            os.environ["BROWSER_USE_DISABLE_EXTENSIONS"] = "1"

        if browser_config.disable_cloud:
            os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
            os.environ.pop("BROWSER_USE_API_KEY", None)

        if browser_config.disable_telemetry:
            os.environ["ANONYMIZED_TELEMETRY"] = "false"

        os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "result")

        start_timeout = str(browser_config.browser_start_timeout)
        os.environ.setdefault("TIMEOUT_BrowserStartEvent", start_timeout)
        os.environ.setdefault("TIMEOUT_BrowserLaunchEvent", start_timeout)

        import uuid

        browser_runtime_dir = browser_config.runtime_dir or str(get_browser_runtime_dir())
        browser_extensions_dir = browser_config.extensions_dir or str(get_browser_extensions_dir())
        run_id = uuid.uuid4().hex[:8]

        ephemeral_profile_dir: str | None = None
        if browser_config.user_data_dir:
            browser_user_data_dir = browser_config.user_data_dir
        elif browser_config.profile_mode == "ephemeral":
            profile_name = f"session-{uuid.uuid4().hex[:12]}"
            browser_user_data_dir = str(get_browser_user_data_dir(profile_name))
            ephemeral_profile_dir = browser_user_data_dir
            _log_browser_event(
                "profile_ephemeral",
                run_id=run_id,
                profile=profile_name,
            )
        else:
            browser_user_data_dir = str(get_browser_user_data_dir())

        os.environ["BROWSER_USE_CONFIG_DIR"] = browser_runtime_dir
        os.environ["BROWSER_USE_PROFILES_DIR"] = browser_user_data_dir
        os.environ["BROWSER_USE_EXTENSIONS_DIR"] = browser_extensions_dir

        _suppress_external_browser_loggers()
        output_suppressor = _SuppressOutput()

        run_t0 = time.perf_counter()
        result = _NO_EXTRACTED_CONTENT
        run_success = True

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

                model_name, llm_base_url, llm_api_key = _resolve_browser_llm_credentials(
                    soothe_config=soothe_config,
                )

                _log_browser_event(
                    "run_start",
                    run_id=run_id,
                    task_len=len(task) if isinstance(task, str) else 0,
                    headless=headless,
                    max_steps=resolved_max_steps,
                    use_vision=use_vision,
                    model=model_name,
                    model_role=browser_use_model_role(soothe_config),
                    base_url=preview_first(str(llm_base_url or ""), 80) or "(default)",
                )
                _log_browser_event(
                    "task_preview",
                    run_id=run_id,
                    preview=preview_first(str(task), 400),
                )

                llm_kwargs: dict[str, Any] = {"model": model_name}
                if llm_base_url:
                    llm_kwargs["base_url"] = llm_base_url
                if llm_api_key:
                    llm_kwargs["api_key"] = llm_api_key

                from browser_use.llm import ChatOpenAI as BrowserChatOpenAI

                llm = BrowserChatOpenAI(**llm_kwargs)

                cdp_url = None
                if browser_config.enable_existing_browser:
                    use_existing = await detect_existing_browser_intent(
                        task,
                        soothe_config=soothe_config,
                    )
                    if use_existing:
                        cdp_url = os.environ.get("CHROME_CDP_URL")
                        if cdp_url:
                            _log_browser_event(
                                "existing_browser_connect",
                                run_id=run_id,
                                cdp_url=cdp_url,
                            )
                        else:
                            _log_browser_event(
                                "existing_browser_unavailable",
                                run_id=run_id,
                                reason="CHROME_CDP_URL missing",
                            )

                if not cdp_url:
                    killed = cleanup_stale_chrome(browser_user_data_dir)
                    if killed:
                        import asyncio

                        _log_browser_event(
                            "stale_chrome_cleanup",
                            run_id=run_id,
                            killed=killed,
                        )
                        await asyncio.sleep(1)

                extra_args = [f"--user-data-dir={browser_user_data_dir}"]
                browser_instance = Browser(
                    headless=headless if not cdp_url else False,
                    cdp_url=cdp_url,
                    args=extra_args,
                    user_data_dir=browser_user_data_dir,
                )
                _log_browser_event(
                    "browser_ready",
                    run_id=run_id,
                    cdp_url=cdp_url or "",
                    headless_effective=headless if not cdp_url else False,
                    user_data_dir=preview_first(str(browser_user_data_dir), 120),
                )

                last_step_wall = time.perf_counter()

                async def on_step_end(agent: Any) -> None:
                    nonlocal last_step_wall
                    step_num = agent.state.n_steps
                    last = agent.history.history[-1] if agent.history.history else None
                    tool_name = "Step"
                    action_desc = ""
                    page_title = ""
                    url = None
                    if last:
                        if hasattr(last, "model_output") and last.model_output:
                            action = getattr(last.model_output, "action", None)
                            if action is not None:
                                tool_name, action_desc = summarize_browser_step_action(action)
                        if hasattr(last, "state"):
                            url = getattr(last.state, "url", None)
                            page_title = preview_first(getattr(last.state, "title", ""), 60)
                    if not action_desc and url:
                        action_desc = preview_first(str(url), 100)
                        if tool_name == "Step":
                            tool_name = "Navigate"
                    now = time.perf_counter()
                    wall_since_prev = now - last_step_wall
                    last_step_wall = now
                    _log_browser_event(
                        "step",
                        run_id=run_id,
                        step=step_num,
                        dt_s=round(wall_since_prev, 2),
                        elapsed_s=round(now - run_t0, 1),
                        url=url or "",
                        title=page_title,
                        action=action_desc or "(none)",
                        tool=tool_name,
                        done=agent.history.is_done(),
                        history_len=len(agent.history.history) if agent.history.history else 0,
                    )
                    emit_subagent_wire_event(
                        BrowserUseStepCompletedEvent(
                            step_index=int(step_num),
                            tool_name=tool_name,
                            url=str(url or ""),
                            title=str(page_title),
                            action_preview=str(action_desc or "")[:120],
                            status="done",
                            duration_ms=int(wall_since_prev * 1000),
                        ).to_dict(),
                        logger,
                    )

                agent = BrowserAgent(
                    task=task,
                    llm=llm,
                    browser=browser_instance,
                    use_vision=use_vision,
                )

                _log_browser_event("session_start_begin", run_id=run_id)
                sess_t0 = time.perf_counter()
                await agent.browser_session.start()
                _log_browser_event(
                    "session_start_end",
                    run_id=run_id,
                    dt_s=round(time.perf_counter() - sess_t0, 2),
                )

                for step_idx in range(resolved_max_steps):
                    try:
                        iter_t0 = time.perf_counter()
                        _log_browser_event(
                            "step_begin",
                            run_id=run_id,
                            step=step_idx + 1,
                            max_steps=resolved_max_steps,
                            elapsed_s=round(iter_t0 - run_t0, 1),
                        )
                        await agent.step()
                        _log_browser_event(
                            "step_end",
                            run_id=run_id,
                            step=step_idx + 1,
                            dt_s=round(time.perf_counter() - iter_t0, 2),
                        )
                        await on_step_end(agent)
                        if agent.history.is_done():
                            _log_browser_event(
                                "run_done",
                                run_id=run_id,
                                step=step_idx + 1,
                            )
                            break
                    except Exception:
                        logger.exception("browser_use event=step_failed run_id=%s", run_id)
                        raise

                history = agent.history
                steps_executed = len(history.history) if history.history else 0
                extracted = history.final_result()
                if extracted:
                    result = str(extracted)
                elif _browser_history_had_no_progress(history):
                    result = _format_browser_no_progress_error(
                        model_name=model_name,
                        steps=steps_executed,
                    )
                    run_success = False
                    logger.error(
                        "browser_use event=no_progress run_id=%s model=%s steps=%d",
                        run_id,
                        model_name,
                        steps_executed,
                    )
                else:
                    result = _NO_EXTRACTED_CONTENT
                    run_success = False
                    logger.error(
                        "browser_use event=no_content run_id=%s steps=%d model=%s",
                        run_id,
                        steps_executed,
                        model_name,
                    )
                raw_result = str(result)
                history_digest = _history_digest_for_synthesis(history)
                synthesis_decision = await _synthesize_browser_use_result(
                    task=str(task or ""),
                    raw_result=raw_result,
                    history_digest=history_digest,
                    soothe_config=soothe_config,
                    browser_config=browser_config,
                    run_id=run_id,
                )
                result_str, completion_summary, used_synthesized, quality_sufficient = (
                    _apply_browser_use_synthesis_decision(
                        raw_result=raw_result,
                        decision=synthesis_decision,
                    )
                )
                if used_synthesized:
                    _log_browser_event("synthesis_applied", run_id=run_id)
                if not run_success and quality_sufficient:
                    run_success = True
                result = result_str
                _log_browser_event(
                    "run_end",
                    run_id=run_id,
                    total_s=round(time.perf_counter() - run_t0, 1),
                    steps=steps_executed,
                    success=run_success,
                    result_preview=preview_first(result_str, 300),
                )

                emit_subagent_wire_event(
                    BrowserUseCompletedEvent(
                        duration_ms=int((time.perf_counter() - run_t0) * 1000),
                        success=run_success,
                        summary=completion_summary,
                    ).to_dict(),
                    logger,
                )

                try:
                    _log_browser_event("session_stop_begin", run_id=run_id)
                    await agent.browser_session.stop()
                except Exception:
                    _log_browser_event("session_stop_skip", run_id=run_id, reason="already stopped")

                if browser_config.cleanup_on_exit:
                    cleanup_browser_temp_files()
                    _log_browser_event("temp_cleanup", run_id=run_id)

        except Exception as e:
            logger.exception("browser_use event=run_failed run_id=%s", run_id)
            error_msg = format_cli_error(e)
            result = error_msg
            run_success = False

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
                _log_browser_event(
                    "profile_cleanup",
                    run_id=run_id,
                    dir=ephemeral_profile_dir,
                )

        return {
            "messages": [AIMessage(content=result)],
            "answer": result,
        }

    async def run_browser_use(state: _BrowserUseState) -> dict[str, Any]:
        """Async browser_use function for LangGraph."""
        return await _run_browser_use_async(state)

    graph = StateGraph(_BrowserUseState)
    graph.add_node("run_browser_use", run_browser_use)
    graph.add_edge(START, "run_browser_use")
    graph.add_edge("run_browser_use", END)
    return graph.compile()


def create_browser_use_subagent(
    *,
    headless: bool = True,
    max_steps: int | None = None,
    use_vision: bool = True,
    config: BrowserUseSubagentConfig | None = None,
    soothe_config: Any,
) -> CompiledSubAgent:
    """Create a BrowserUse subagent (CompiledSubAgent with browser-use workflow).

    Args:
        headless: Run browser in headless mode.
        max_steps: Maximum browser agent steps. When ``None``, uses
            ``BrowserUseSubagentConfig.max_steps`` (default 10).
        use_vision: Enable vision/screenshot support.
        config: BrowserUse subagent configuration object with runtime directories,
            cleanup settings, and feature flags.
        soothe_config: SootheConfig used to resolve ``subagents.browser_use.model_role``.

    Returns:
        `CompiledSubAgent` dict compatible with soothe_deepagents.
    """
    runnable = _build_browser_use_graph(
        headless=headless,
        max_steps=max_steps,
        use_vision=use_vision,
        config=config,
        soothe_config=soothe_config,
    )

    return {
        "name": "browser_use",
        "description": BROWSER_DESCRIPTION,
        "runnable": runnable,
    }
