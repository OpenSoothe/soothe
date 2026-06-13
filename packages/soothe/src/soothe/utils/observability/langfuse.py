"""Merge Langfuse LangChain callbacks into RunnableConfig for LangGraph streams (IG-367)."""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_ENV_REF = re.compile(r"^\$\{(\w+)\}$")
_INIT_LOCK = threading.Lock()
_CLIENT_INITIALIZED_FOR_PUBLIC_KEY: set[str] = set()
_HANDLERS: dict[str, Any] = {}
# Thread pool for non-blocking Langfuse initialization (prevents event loop blocking)
_LANGFUSE_EXECUTOR: ThreadPoolExecutor | None = None
# Cache warning state - emit once per session instead of 15+ times per query
_LANGFUSE_NOT_INSTALLED_WARNED = False
_LANGFUSE_HANDLER_UNAVAILABLE_WARNED = False


def _resolved_langfuse_tags(soothe_config: SootheConfig) -> list[str] | None:
    """Normalize ``observability.langfuse.tags`` to non-empty stripped strings."""
    raw = soothe_config.observability.langfuse.tags
    if not raw:
        return None
    out = [str(t).strip() for t in raw if str(t).strip()]
    return out or None


def _resolve_str(value: str | None) -> str | None:
    """Strip and resolve ``${ENV}`` placeholders; return None if unresolved or empty."""
    from soothe.config.env import _resolve_env

    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    out = _resolve_env(s)
    if _ENV_REF.match(out):
        return None
    return out


def resolve_langfuse_config_str(value: str | None) -> str | None:
    """Public wrapper for Langfuse YAML/env field resolution (keys, host, etc.)."""
    return _resolve_str(value)


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the thread pool executor for Langfuse initialization."""
    global _LANGFUSE_EXECUTOR
    if _LANGFUSE_EXECUTOR is None:
        _LANGFUSE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="langfuse-init")
    return _LANGFUSE_EXECUTOR


def _init_langfuse_client_sync(kwargs: dict[str, Any]) -> None:
    """Synchronous Langfuse client initialization (runs in thread pool)."""
    from langfuse import Langfuse

    Langfuse(**kwargs)


def _ensure_langfuse_client(soothe_config: SootheConfig) -> None:
    """Register a Langfuse SDK client when both public and secret keys are configured.

    This function is called from sync context (e.g., during model creation or config building).
    Runs initialization in a background thread WITHOUT blocking the calling thread.
    The Langfuse client will be initialized asynchronously; callbacks will still work
    because the handler references the client lazily.
    """
    lf = soothe_config.observability.langfuse
    pub = _resolve_str(lf.public_key)
    sec = _resolve_str(lf.secret_key)
    if not pub or not sec:
        return
    with _INIT_LOCK:
        if pub in _CLIENT_INITIALIZED_FOR_PUBLIC_KEY:
            return

        # Mark as initializing immediately to prevent duplicate attempts
        _CLIENT_INITIALIZED_FOR_PUBLIC_KEY.add(pub)

        kwargs: dict[str, Any] = {"public_key": pub, "secret_key": sec}
        host = _resolve_str(lf.host)
        if host:
            kwargs["host"] = host
        if lf.environment:
            env_label = _resolve_str(lf.environment)
            if env_label:
                kwargs["environment"] = env_label
        if lf.release:
            rel = _resolve_str(lf.release)
            if rel:
                kwargs["release"] = rel
        if lf.sample_rate is not None:
            kwargs["sample_rate"] = float(lf.sample_rate)

        # Submit to background thread WITHOUT waiting - non-blocking
        executor = _get_executor()
        executor.submit(_init_langfuse_client_sync, kwargs)
        logger.debug("Langfuse client initialization submitted to background thread")


async def _ensure_langfuse_client_async(soothe_config: SootheConfig) -> None:
    """Async version of Langfuse client initialization for use in async context.

    Runs the initialization in a thread pool executor without blocking the event loop.
    The actual initialization happens in background; we don't wait for completion.
    """
    _ensure_langfuse_client(soothe_config)  # Already non-blocking now


def _langfuse_callback_handler(soothe_config: SootheConfig) -> Any | None:
    global _LANGFUSE_NOT_INSTALLED_WARNED, _LANGFUSE_HANDLER_UNAVAILABLE_WARNED
    lf = soothe_config.observability.langfuse
    try:
        import langfuse.langchain  # noqa: F401 - optional extra soothe[langfuse]
    except ImportError:
        if not _LANGFUSE_NOT_INSTALLED_WARNED:
            logger.warning(
                "observability.langfuse.enabled is true but langfuse is not installed; "
                "install optional dependency (e.g. pip install 'soothe[langfuse]')"
            )
            _LANGFUSE_NOT_INSTALLED_WARNED = True
        return None

    _ensure_langfuse_client(soothe_config)
    pub_resolved = _resolve_str(lf.public_key)
    cache_key = pub_resolved or "__env__"
    with _INIT_LOCK:
        if cache_key not in _HANDLERS:
            from soothe.utils.observability.langfuse_callback_handler import (
                LANGFUSE_AVAILABLE,
                SootheLangfuseCallbackHandler,
            )

            if not LANGFUSE_AVAILABLE:
                if not _LANGFUSE_HANDLER_UNAVAILABLE_WARNED:
                    logger.warning(
                        "observability.langfuse.enabled is true but Langfuse callback handler "
                        "is unavailable; ensure langfuse and langchain are both installed"
                    )
                    _LANGFUSE_HANDLER_UNAVAILABLE_WARNED = True
                return None

            if pub_resolved:
                try:
                    _HANDLERS[cache_key] = SootheLangfuseCallbackHandler(public_key=pub_resolved)
                except TypeError:
                    logger.warning(
                        "Langfuse callback handler does not accept public_key; "
                        "falling back to default constructor"
                    )
                    _HANDLERS[cache_key] = SootheLangfuseCallbackHandler()
            else:
                _HANDLERS[cache_key] = SootheLangfuseCallbackHandler()
        return _HANDLERS[cache_key]


def _create_fresh_langfuse_handler(soothe_config: SootheConfig) -> Any | None:
    """Create a new Langfuse handler instance (not cached) for independent traces.

    Used for LLM calls that should be standalone root traces, not nested under
    subsequent graph invocations. Each call creates a fresh handler with its own
    trace_id and OpenTelemetry context, preventing unwanted nesting.

    Args:
        soothe_config: Active Soothe configuration.

    Returns:
        New SootheLangfuseCallbackHandler instance, or None if Langfuse is disabled/unavailable.
    """
    global _LANGFUSE_NOT_INSTALLED_WARNED, _LANGFUSE_HANDLER_UNAVAILABLE_WARNED
    lf = soothe_config.observability.langfuse
    try:
        import langfuse.langchain  # noqa: F401 - optional extra soothe[langfuse]
    except ImportError:
        if not _LANGFUSE_NOT_INSTALLED_WARNED:
            logger.warning(
                "observability.langfuse.enabled is true but langfuse is not installed; "
                "install optional dependency (e.g. pip install 'soothe[langfuse]')"
            )
            _LANGFUSE_NOT_INSTALLED_WARNED = True
        return None

    _ensure_langfuse_client(soothe_config)

    from soothe.utils.observability.langfuse_callback_handler import (
        LANGFUSE_AVAILABLE,
        SootheLangfuseCallbackHandler,
    )

    if not LANGFUSE_AVAILABLE:
        if not _LANGFUSE_HANDLER_UNAVAILABLE_WARNED:
            logger.warning(
                "observability.langfuse.enabled is true but Langfuse callback handler "
                "is unavailable; ensure langfuse and langchain are both installed"
            )
            _LANGFUSE_HANDLER_UNAVAILABLE_WARNED = True
        return None

    pub_resolved = _resolve_str(lf.public_key)
    # Create fresh handler (not cached) - each call gets independent trace context
    if pub_resolved:
        try:
            return SootheLangfuseCallbackHandler(public_key=pub_resolved)
        except TypeError:
            logger.warning(
                "Langfuse callback handler does not accept public_key; "
                "falling back to default constructor"
            )
            return SootheLangfuseCallbackHandler()
    return SootheLangfuseCallbackHandler()


def merge_langfuse_runnable_config(
    base: dict[str, Any],
    soothe_config: SootheConfig,
    *,
    session_id: str | None = None,
    run_name: str | None = None,
    loop_id: str | None = None,
    inherit_callbacks_from: dict[str, Any] | None = None,
    fresh_handler: bool = False,
) -> dict[str, Any]:
    """Return Runnable config like ``base`` with Langfuse callbacks and session metadata merged in.

    When Langfuse is disabled, missing, or the package is not installed, returns ``base``
    unchanged (same object).

    Args:
        base: RunnableConfig-compatible dict (e.g. ``{"configurable": {...}}``).
        soothe_config: Active Soothe configuration.
        session_id: Optional thread id stored as ``langfuse_session_id`` metadata.
        run_name: Optional root run name (e.g. ``soothe-dev:plan-assess``, ``soothe-dev:execute-step``). When omitted,
            uses ``observability.langfuse.trace_name`` when set.
        loop_id: Optional loop identifier for trace correlation across sub-traces.
        inherit_callbacks_from: When set and already carries the same ``SootheLangfuseCallbackHandler``
            instance as would be attached, skip appending the handler again so a later
            ``merge_configs(langgraph_parent, child)`` does not register duplicate Langfuse
            callbacks (goal-completion synthesis nested under the StrangeLoop graph).
        fresh_handler: When True, creates a new handler instance (not cached) to ensure
            independent trace_id and avoid OpenTelemetry context nesting. Use for
            standalone LLM calls that should not nest under subsequent graph traces.

    When ``observability.langfuse.tags`` / ``user_id`` are set, merges ``langfuse_tags`` /
    ``langfuse_user_id`` into metadata if those keys are not already present (Langfuse
    LangChain ``CallbackHandler`` reads them for trace attributes and Cost Dashboard filters).

    Returns:
        New dict with merged ``callbacks`` / ``metadata`` / ``run_name``, or ``base``.
    """
    if not soothe_config.observability.langfuse.enabled:
        return base
    # Use fresh handler for independent traces (e.g., intent classification before agent-loop-graph)
    handler = (
        _create_fresh_langfuse_handler(soothe_config)
        if fresh_handler
        else _langfuse_callback_handler(soothe_config)
    )
    if handler is None:
        return base
    skip_handler_append = False
    if inherit_callbacks_from is not None:
        existing = _langfuse_handler_from_runnable_config(inherit_callbacks_from)
        if existing is not None and existing is handler:
            skip_handler_append = True
    out: dict[str, Any] = dict(base)
    if "configurable" in base:
        out["configurable"] = dict(base["configurable"])
    if not skip_handler_append:
        prev = list(out.get("callbacks") or [])
        out["callbacks"] = prev + [handler]
    meta = dict(out.get("metadata") or {})
    if session_id:
        meta.setdefault("langfuse_session_id", session_id)
        # Align callback metadata with configurable.thread_id for system-prompt hints (IG-385).
        meta.setdefault("thread_id", session_id)
    if loop_id:
        meta.setdefault("loop_id", loop_id)
    tags_cfg = _resolved_langfuse_tags(soothe_config)
    if tags_cfg is not None and "langfuse_tags" not in meta:
        meta["langfuse_tags"] = tags_cfg
    uid = _resolve_str(soothe_config.observability.langfuse.user_id)
    if uid and "langfuse_user_id" not in meta:
        meta["langfuse_user_id"] = uid
    if meta:
        out["metadata"] = meta
    name = (run_name or "").strip()
    if not name:
        name = (soothe_config.observability.langfuse.trace_name or "").strip()
    if name:
        out["run_name"] = name
        # Langfuse SDK v3 reads trace title from metadata (not Runnable run_name alone).
        meta.setdefault("langfuse_trace_name", name)
    return out


def _iter_callback_handlers(callbacks: Any) -> list[Any]:
    """Flatten LangChain ``callbacks`` (list or ``CallbackManager``) to handler instances."""
    out: list[Any] = []
    if callbacks is None:
        return out
    if isinstance(callbacks, (list, tuple)):
        for item in callbacks:
            out.extend(_iter_callback_handlers(item))
        return out
    nested = getattr(callbacks, "handlers", None)
    if isinstance(nested, (list, tuple)):
        for h in nested:
            out.extend(_iter_callback_handlers(h))
        return out
    out.append(callbacks)
    return out


def _langfuse_handler_from_runnable_config(config: dict[str, Any]) -> Any | None:
    """Return the Soothe Langfuse LangChain handler from RunnableConfig if present."""
    from soothe.utils.observability.langfuse_callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    for h in _iter_callback_handlers(config.get("callbacks")):
        if isinstance(h, SootheLangfuseCallbackHandler):
            return h
    return None


def build_traced_config(
    soothe_config: SootheConfig | None,
    *,
    purpose: str,
    component: str,
    phase: str = "pre-stream",
    session_id: str | None = None,
    run_name: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    loop_id: str | None = None,
    independent_trace: bool = False,
) -> dict[str, Any]:
    """Build a RunnableConfig with Langfuse callbacks and standardized call metadata.

    Combines ``merge_langfuse_runnable_config`` with ``create_llm_call_metadata`` so
    non-agentloop LLM call sites get both observability metadata and Langfuse tracing
    in a single call.

    Args:
        soothe_config: Active Soothe configuration (None disables Langfuse merge).
        purpose: Call purpose (classify, vision_preflight, reflection, etc.).
        component: Component identifier (classifier.intent, daemon.vision, etc.).
        phase: Execution phase (pre-stream, post-loop, etc.).
        session_id: Thread id for Langfuse session correlation.
        run_name: Trace display name (e.g. ``soothe:intent-classify``).
        extra_metadata: Additional metadata fields to merge.
        loop_id: Optional loop identifier for trace correlation across sub-traces.
        independent_trace: When True, creates a fresh handler with new trace_id to avoid
            nesting under a prior trace's OpenTelemetry context. Use for LLM calls that
            should be standalone root traces (e.g., intent classification before agent-loop-graph).

    Returns:
        RunnableConfig dict with callbacks and metadata ready for ``model.ainvoke(..., config=)``.
    """
    from soothe.middleware._utils import create_llm_call_metadata

    metadata = create_llm_call_metadata(purpose=purpose, component=component, phase=phase)
    if extra_metadata:
        metadata.update(extra_metadata)

    base: dict[str, Any] = {"metadata": metadata}

    if soothe_config is None:
        return base

    if independent_trace:
        return merge_langfuse_runnable_config(
            base,
            soothe_config,
            session_id=session_id,
            run_name=run_name,
            loop_id=loop_id,
            fresh_handler=True,
        )

    return merge_langfuse_runnable_config(
        base,
        soothe_config,
        session_id=session_id,
        run_name=run_name,
        loop_id=loop_id,
    )


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Same root run label as ``build_loop_graph_invoke_config`` / LangGraph ``run_name``."""
    tn = (trace_name or "").strip()
    return f"{tn}:strange-loop-graph" if tn else "strange-loop-graph"


def _merge_trace_fields_via_ingestion(
    client: Any,
    *,
    trace_id: str,
    display_name: str,
    input_text: str,
    output_text: str,
    session_id: str | None,
) -> bool:
    """Enqueue a Langfuse ``trace-create`` merge event (SDK-internal; mirrors tag updates).

    Returns:
        True if an event was queued on the client's resource manager.
    """
    resources = getattr(client, "_resources", None)
    if resources is None:
        return False
    try:
        from langfuse._utils import _get_timestamp
        from langfuse.api.resources.ingestion.types.trace_body import TraceBody

        kwargs: dict[str, Any] = {
            "id": trace_id,
            "name": display_name,
            "input": input_text,
            "output": output_text,
        }
        if session_id:
            kwargs["session_id"] = session_id
        body = TraceBody(**kwargs)
        event = {
            "id": client.create_trace_id(),
            "type": "trace-create",
            "timestamp": _get_timestamp(),
            "body": body,
        }
        resources.add_trace_task(event)
        return True
    except Exception:
        logger.debug("Langfuse trace ingestion merge failed", exc_info=True)
        return False


def patch_langfuse_trace_goal_io(
    config: dict[str, Any],
    *,
    goal_text: str,
    output_text: str,
    trace_display_name: str,
    public_key: str | None = None,
    session_id: str | None = None,
) -> None:
    """Set Langfuse trace-level ``name`` / ``input`` / ``output`` for the loop graph run (IG-395).

    Prefer merging via the Langfuse ingestion ``trace-create`` path so the trace row keeps the
    StrangeLoop display name and does not gain an extra ``soothe-goal-trace-io`` observation.
    Falls back to ``start_span(...).update_trace(...)`` when ingestion is unavailable.

    Args:
        config: RunnableConfig passed to ``CompiledGraph.ainvoke`` (must include Langfuse handler).
        goal_text: User goal string for trace input.
        output_text: Final user-visible answer for trace output (may be empty).
        trace_display_name: Root trace title (must match graph ``run_name``, e.g. ``…:agent-loop-graph``).
        public_key: Resolved Langfuse public key for ``get_client`` (multi-project safe).
        session_id: Conversation thread id for Langfuse session correlation (optional).
    """
    handler = _langfuse_handler_from_runnable_config(config)
    if handler is None:
        return
    trace_id = getattr(handler, "last_trace_id", None)
    if not trace_id:
        return
    try:
        from langfuse import get_client

        client = get_client(public_key=public_key) if public_key else get_client()

        merged = _merge_trace_fields_via_ingestion(
            client,
            trace_id=trace_id,
            display_name=trace_display_name,
            input_text=goal_text,
            output_text=output_text,
            session_id=session_id,
        )
        if not merged:
            span = client.start_span(
                trace_context={"trace_id": trace_id},
                name=trace_display_name,
            )
            span.update_trace(
                name=trace_display_name,
                input=goal_text,
                output=output_text,
            )
            span.end()
        client.flush()
    except Exception:
        logger.debug(
            "Langfuse trace goal I/O patch failed (non-fatal)",
            exc_info=True,
        )
