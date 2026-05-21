"""CodeInterpreterMiddleware -- embedded QuickJS interpreter for programmatic tool calling.

IG-423: Integrates deepagents CodeInterpreterMiddleware for stateful code execution
within the agent loop. Enables programmatic tool calling (PTC) pattern where agents
write code that calls tools directly, reducing token usage and enabling better
control flow.

Reference: https://www.langchain.com/blog/give-your-agents-an-interpreter
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class CodeInterpreterMiddleware(AgentMiddleware):
    """Embedded QuickJS interpreter for programmatic tool calling.

    This middleware wraps the deepagents CodeInterpreterMiddleware (via
    langchain_quickjs) to provide:

    - Stateful code execution: Variables persist across eval calls (REPL-like)
    - Programmatic Tool Calling (PTC): Tools exposed via tools.* namespace
    - Reduced token usage: Intermediate results stay in interpreter state
    - Better control flow: Agents write code for multi-step logic

    The interpreter is intentionally limited by design:
    - No filesystem, network, or shell access by default
    - Only language features (objects, arrays, maps, JSON)
    - Capabilities exposed through explicit bridges (ptc_allowlist)

    Configuration via SootheConfig.code_interpreter:
        enabled: Enable the middleware (default: False, opt-in)
        ptc_allowlist: Tools exposed via tools.* namespace (default: [])
        memory_limit_mb: Memory limit (default: 128)
        timeout_seconds: Per-eval timeout (default: 30)
        max_ptc_calls: Max programmatic tool calls per eval (default: 50)
        max_result_size: Max result size in chars (default: 10000)
        console_capture: Capture console.log output (default: True)
        snapshot_between_turns: Preserve state between turns (default: False)

    Example usage in agent code:
        ```javascript
        // Programmatic tool calling with PTC
        const topics = ["retrieval", "memory", "evaluation"];
        const reports = await Promise.all(
            topics.map(topic => tools.task({
                description: `Research ${topic}`,
                subagent_type: "general-purpose"
            }))
        );
        reports.join("\\n\\n");
        ```
    """

    def __init__(
        self,
        config: SootheConfig | None = None,
        ptc_allowlist: list[str] | None = None,
        memory_limit_mb: int = 128,
        timeout_seconds: int = 30,
        max_ptc_calls: int = 50,
        max_result_size: int = 10000,
        console_capture: bool = True,
        snapshot_between_turns: bool = False,
    ) -> None:
        """Initialize the code interpreter middleware.

        Args:
            config: Soothe configuration. If provided, other args are overridden
                by config.code_interpreter values.
            ptc_allowlist: List of tool names exposed via tools.* namespace.
            memory_limit_mb: Interpreter memory limit in MB.
            timeout_seconds: Per-eval timeout in seconds.
            max_ptc_calls: Maximum programmatic tool calls per eval.
            max_result_size: Maximum result size in characters.
            console_capture: Capture console.log output.
            snapshot_between_turns: Preserve state between conversation turns.
        """
        # Use config values if provided, otherwise use explicit args
        if config is not None:
            ci_config = config.code_interpreter
            self._ptc_allowlist = ci_config.ptc_allowlist
            self._memory_limit_mb = ci_config.memory_limit_mb
            self._timeout_seconds = ci_config.timeout_seconds
            self._max_ptc_calls = ci_config.max_ptc_calls
            self._max_result_size = ci_config.max_result_size
            self._console_capture = ci_config.console_capture
            self._snapshot_between_turns = ci_config.snapshot_between_turns
        else:
            self._ptc_allowlist = ptc_allowlist or []
            self._memory_limit_mb = memory_limit_mb
            self._timeout_seconds = timeout_seconds
            self._max_ptc_calls = max_ptc_calls
            self._max_result_size = max_result_size
            self._console_capture = console_capture
            self._snapshot_between_turns = snapshot_between_turns

        self._inner_middleware: AgentMiddleware | None = None

    def _initialize_inner(self) -> AgentMiddleware | None:
        """Initialize the underlying deepagents CodeInterpreterMiddleware.

        Returns:
            The initialized middleware or None if langchain_quickjs is not available.
        """
        if self._inner_middleware is not None:
            return self._inner_middleware

        try:
            # Try to import from langchain_quickjs (the deepagents integration)
            from langchain_quickjs import CodeInterpreterMiddleware as QuickJSMiddleware

            self._inner_middleware = QuickJSMiddleware(
                ptc=self._ptc_allowlist,
                memory_limit_mb=self._memory_limit_mb,
                timeout_seconds=self._timeout_seconds,
                max_ptc_calls=self._max_ptc_calls,
                max_result_size=self._max_result_size,
                console_capture=self._console_capture,
                snapshot_between_turns=self._snapshot_between_turns,
            )
            logger.info(
                "[CodeInterpreter] Initialized with ptc_allowlist=%s, memory=%dMB, timeout=%ds",
                self._ptc_allowlist,
                self._memory_limit_mb,
                self._timeout_seconds,
            )
            return self._inner_middleware
        except ImportError:
            logger.warning(
                "[CodeInterpreter] langchain_quickjs not installed. "
                "Install with: uv add 'deepagents[quickjs]'"
            )
            return None

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Hook called before agent execution.

        Delegates to inner middleware if initialized.
        """
        inner = self._initialize_inner()
        if inner is not None:
            return await inner.abefore_agent(state, runtime)
        return None

    async def aafter_agent(
        self,
        state: AgentState,
        runtime: Runtime,
        output: Any,
    ) -> Any:
        """Hook called after agent execution.

        Delegates to inner middleware if initialized.
        """
        inner = self._initialize_inner()
        if inner is not None:
            return await inner.aafter_agent(state, runtime, output)
        return output

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Any,
    ) -> Any:
        """Hook called for tool call wrapping.

        Delegates to inner middleware if initialized.
        """
        inner = self._initialize_inner()
        if inner is not None:
            return await inner.awrap_tool_call(request, handler)
        return await handler(request)

    async def awrap_llm_call(
        self,
        request: Any,
        handler: Any,
    ) -> Any:
        """Hook called for LLM call wrapping.

        Delegates to inner middleware if initialized.
        """
        inner = self._initialize_inner()
        if inner is not None:
            return await inner.awrap_llm_call(request, handler)
        return await handler(request)
