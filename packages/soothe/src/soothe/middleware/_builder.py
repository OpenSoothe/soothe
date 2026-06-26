"""Middleware stack construction for CoreAgent.

Defines the Soothe middleware layer.
Note: ParallelToolsMiddleware removed - langchain handles tool parallelism
via asyncio.gather in ToolNode.

This module provides a single function to build the middleware stack
in the correct order with proper dependency handling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentMiddleware

    from soothe.config import SootheConfig
    from soothe.middleware._tool_context import ToolContextRegistry, ToolTriggerRegistry
    from soothe.middleware.identity import IdentityRuntime
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)


def _build_tool_registries(
    config: SootheConfig,
) -> tuple[ToolTriggerRegistry | None, ToolContextRegistry | None]:
    """Create tool trigger and context registries.

    Args:
        config: Soothe configuration.

    Returns:
        Tuple of (trigger_registry, context_registry), or (None, None) if not configured.
    """
    # Tool registries always created (optimizations always enabled)
    try:
        from soothe.middleware._tool_context import ToolContextRegistry, ToolTriggerRegistry
        from soothe.plugin.global_registry import get_plugin_registry

        plugin_registry = get_plugin_registry()

        trigger_registry = ToolTriggerRegistry(plugin_registry)
        context_registry = ToolContextRegistry(config, plugin_registry)

        logger.debug("[Middleware] Tool registries created for dynamic context injection")
        return trigger_registry, context_registry
    except RuntimeError:
        # Plugin registry not initialized, skip tool registries
        logger.debug(
            "[Middleware] Plugin registry not available, dynamic context injection disabled"
        )
        return None, None


def build_soothe_middleware_stack(
    config: SootheConfig,
    policy: PolicyProtocol | None,
    mcp_registry: Any | None = None,
    identity_runtime: IdentityRuntime | None = None,
) -> tuple[AgentMiddleware, ...]:
    """Build Soothe middleware stack in correct order.

    The middleware order is intentional and follows dependency requirements:

    0. **IdentityMiddleware** (optional, RFC-307) - Validates JWT auth_token or
       resolves external channel identity BEFORE any other middleware. Must run
       before PolicyMiddleware to establish user context for permission checks.
       Only installed when ``identity_runtime.enabled`` is True.

    1. **SoothePolicyMiddleware** - Blocks unsafe actions FIRST before any
       other middleware processes them. Uses PolicyProtocol.check() on every
       tool/subagent call.

    2. **ToolConcurrencyMiddleware** - Limits concurrent tool calls per thread
       via semaphore. LangChain's ToolNode uses asyncio.gather without limits;
       this middleware bounds parallelism to prevent resource exhaustion.

    3. **SystemPromptMiddleware** - Modifies prompts BEFORE the
       LLM call. Requires ``routing_classification`` state injected by StrangeLoop / runner
       runner during pre-stream phase. Only enabled when performance features
       are fully configured.

    4. **LLMRateLimitMiddleware** - Rate limits LLM API calls at model level,
       not thread level. Uses sliding window for RPM and semaphore for concurrent
       requests. Solves thread hanging issues from thread-level blocking.

    5. **ExecutionHintsMiddleware** - Injects Layer 2 execution hints
       (soothe_step_subagent, soothe_step_expected_output)
       into system prompt via abefore_agent hook. Runs before agent loop starts.

    6. **CodeInterpreterMiddleware** (optional) - Embedded QuickJS interpreter
       for programmatic tool calling. Enabled when ``code_interpreter.enabled``
       is True. Exposes allowlisted tools via ``tools.*`` namespace.

    7. **WorkspaceContextMiddleware** - Sets workspace ContextVar via
       abefore_agent/aafter_agent hooks. Must be set before tools run to
       enable thread-aware filesystem operations.

    8. **PerTurnModelMiddleware** - When ``attach_stream_model_override`` is set
       for the current asyncio Task (daemon per-turn ``input``), replaces the
       chat model for that stream via ``ModelRequest.override``.

    Args:
        config: SootheConfig with performance settings.
        policy: PolicyProtocol instance for safety enforcement.
        mcp_registry: Optional MCPRegistry for MCP tool integration (RFC-412).
        identity_runtime: Optional identity bundle (service, config, thread context).
            When ``enabled`` is True, IdentityMiddleware is prepended to the stack.

    Returns:
        Tuple of middleware instances in execution order.
    """
    from .execution_hints import ExecutionHintsMiddleware
    from .llm_rate_limit import LLMRateLimitMiddleware
    from .model_call_profiler import is_profiler_enabled
    from .per_turn_model import PerTurnModelMiddleware
    from .policy import SoothePolicyMiddleware
    from .system_prompt import SystemPromptMiddleware
    from .tool_concurrency import ToolConcurrencyMiddleware
    from .tool_network_errors import NetworkToolErrorsMiddleware
    from .workspace_context import WorkspaceContextMiddleware

    stack: list[AgentMiddleware] = []
    profile_model_calls = is_profiler_enabled(config)

    # 0. Identity validation (RFC-307: must run before PolicyMiddleware)
    if identity_runtime is not None and identity_runtime.enabled:
        from .identity import IdentityMiddleware

        stack.append(IdentityMiddleware(identity_runtime))
        logger.info("[Middleware] Identity validation enabled (RFC-307)")

    # 0b. Model call profiler (optional, for latency debugging)
    # Insert at the very start to capture full middleware chain timing
    if profile_model_calls:
        from .model_call_profiler import ModelCallProfilerMiddleware

        stack.append(ModelCallProfilerMiddleware(enabled=True))
        logger.info("[Middleware] Model call profiler enabled (outer wrapper)")

    # 1. Policy enforcement (must be first to block unsafe actions)
    if policy:
        stack.append(
            SoothePolicyMiddleware(
                policy=policy,
                profile_name=config.agent.protocols.policy.profile,
            )
        )
        logger.debug("[Middleware] Policy enforcement enabled")

    # 1b. Skill activation (RFC-105: activates conditional skills on file-op path match)
    from soothe.skills.index import SkillIndex
    from soothe.skills.registry import ProgressiveSkillRegistry

    from .skill_activation import SkillActivationMiddleware

    _skill_index = SkillIndex()
    stack.append(
        SkillActivationMiddleware(
            registry=ProgressiveSkillRegistry(),
            catalog_provider=lambda: _skill_index.rebuild_if_stale(),
            config=config,
        )
    )
    logger.info("[Middleware] Skill activation (RFC-105) enabled")

    # 1c. MCP tool search (RFC-412: MCP progressive disclosure telemetry)
    if mcp_registry is not None:
        from .mcp_tool_search import MCPToolSearchMiddleware

        stack.append(MCPToolSearchMiddleware(mcp_registry=mcp_registry))
        logger.info("[Middleware] MCP tool search (RFC-412) enabled")

    # 2. Tool concurrency limit (bounds parallel tool calls per thread)
    stack.append(ToolConcurrencyMiddleware())
    max_parallel_tools = config.agent.loop.concurrency.max_parallel_tools
    logger.info(
        "[Middleware] Tool concurrency enabled: max_parallel_tools=%d",
        max_parallel_tools,
    )

    # 2b. Recoverable outbound network errors → tool messages (TLS verify, connection refused)
    stack.append(NetworkToolErrorsMiddleware())
    logger.debug("[Middleware] Network tool error recovery enabled")

    # 2c. Cap tool output before graph state / model context
    from .tool_output_cap import ToolOutputCapMiddleware

    stack.append(ToolOutputCapMiddleware(config=config))
    logger.debug("[Middleware] Tool output cap enabled")

    # 2d. Progressive builtin-tool loading (optional)
    progressive_tool_middleware = None
    if config.progressive_tools.enabled:
        from .progressive_tools import ProgressiveToolMiddleware

        progressive_tool_middleware = ProgressiveToolMiddleware(config=config)
        stack.append(progressive_tool_middleware)
        logger.info("[Middleware] Progressive tool loading enabled")

    # 3. System prompt assembly (requires routing_classification from StrangeLoop / runner)
    trigger_registry, context_registry = _build_tool_registries(config)

    stack.append(
        SystemPromptMiddleware(
            config=config,
            tool_trigger_registry=trigger_registry,
            tool_context_registry=context_registry,
            mcp_registry=mcp_registry,
            progressive_tool_middleware=progressive_tool_middleware,
        )
    )
    logger.info("[Middleware] System prompt middleware enabled")

    # 3b. Inner profiler (optional, after SystemPrompt, before RateLimiter)
    # Captures timing between prompt modification and rate limiting
    if profile_model_calls:
        from .model_call_profiler import InnerModelCallProfilerMiddleware

        stack.append(InnerModelCallProfilerMiddleware(enabled=True))
        logger.info("[Middleware] Inner model call profiler enabled")

    # 4. LLM rate limiting (throttles API calls, not threads)
    # This prevents thread hanging by blocking only LLM calls, not entire threads
    llm_rl = config.agent.loop.llm_rate_limit
    if llm_rl.enabled:
        stack.append(
            LLMRateLimitMiddleware(
                requests_per_minute=llm_rl.rpm_limit,
                max_concurrent_requests_per_thread=llm_rl.concurrent_limit,
                call_timeout_seconds=llm_rl.call_timeout_seconds,
                call_timeout_max_seconds=llm_rl.call_timeout_max_seconds,
                thread_local=True,
                retry_on_timeout=llm_rl.retry_on_timeout,
                max_timeout_retries=llm_rl.max_timeout_retries,
                timeout_retry_multiplier=llm_rl.timeout_retry_multiplier,
                # IG-499: 429 retry configuration
                retry_on_rate_limit=llm_rl.retry_on_rate_limit,
                max_rate_limit_retries=llm_rl.max_rate_limit_retries,
                rate_limit_backoff_base=llm_rl.rate_limit_backoff_base,
                rate_limit_backoff_max=llm_rl.rate_limit_backoff_max,
                respect_retry_after_header=llm_rl.respect_retry_after_header,
            )
        )
        logger.info(
            "[Middleware] LLM rate limiting enabled (thread-local): rpm=%d, concurrent=%d, "
            "timeout=%ds timeout_cap=%ds retry_timeout=%s max_timeout_retries=%d multiplier=%.1f "
            "retry_429=%s max_429_retries=%d backoff_base=%.1fs backoff_max=%.1fs retry_after_header=%s",
            llm_rl.rpm_limit,
            llm_rl.concurrent_limit,
            llm_rl.call_timeout_seconds,
            llm_rl.call_timeout_max_seconds,
            llm_rl.retry_on_timeout,
            llm_rl.max_timeout_retries,
            llm_rl.timeout_retry_multiplier,
            llm_rl.retry_on_rate_limit,
            llm_rl.max_rate_limit_retries,
            llm_rl.rate_limit_backoff_base,
            llm_rl.rate_limit_backoff_max,
            llm_rl.respect_retry_after_header,
        )
    else:
        logger.debug("[Middleware] LLM rate limiting disabled")

    # 5. Execution hints (Layer 2 → Layer 1 integration)
    stack.append(ExecutionHintsMiddleware())
    logger.debug("[Middleware] Execution hints enabled")

    # 6. Code interpreter (embedded QuickJS for programmatic tool calling)
    ci_config = config.agent.code_interpreter
    if ci_config.enabled and ci_config.ptc_allowlist:
        from .code_interpreter import CodeInterpreterMiddleware

        stack.append(CodeInterpreterMiddleware(config=config))
        logger.info(
            "[Middleware] Code interpreter enabled with ptc_allowlist=%s",
            ci_config.ptc_allowlist,
        )
    elif ci_config.enabled:
        logger.info(
            "[Middleware] Code interpreter skipped (enabled but empty ptc_allowlist; IG-506)"
        )
    else:
        logger.debug("[Middleware] Code interpreter disabled (opt-in)")

    # 7. Workspace context (thread-aware filesystem)
    stack.append(WorkspaceContextMiddleware())
    logger.debug("[Middleware] Workspace context enabled")

    # 7b. LLM profiler (optional, innermost before PerTurnModelMiddleware)
    # Captures timing just before the actual model.ainvoke call
    if profile_model_calls:
        from .model_call_profiler import LLMCallProfilerMiddleware

        stack.append(LLMCallProfilerMiddleware(enabled=True))
        logger.info("[Middleware] LLM call profiler enabled (innermost wrapper)")

    # 8. Per-turn model override (daemon / stream context) — innermost around the LLM
    stack.append(PerTurnModelMiddleware(config))
    logger.debug("[Middleware] Per-turn model override enabled")

    return tuple(stack)
