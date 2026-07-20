"""CodeInterpreterMiddleware -- embedded QuickJS interpreter for programmatic tool calling.

IG-423: Integrates CodeInterpreterMiddleware for stateful code execution
within the agent loop. Enables programmatic tool calling (PTC) pattern where agents
write code that calls tools directly, reducing token usage and enabling better
control flow.

Reference: https://www.langchain.com/blog/give-your-agents-an-interpreter
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe_nano.config.constants import DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime
    from langgraph.types import Command

    from soothe_nano.config import SootheConfig
else:
    from langgraph.types import Command

logger = logging.getLogger(__name__)


class CodeInterpreterMiddleware(AgentMiddleware):
    """Embedded QuickJS interpreter for programmatic tool calling.

    This middleware wraps the CodeInterpreterMiddleware (via
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
        max_result_size: Max result size in chars (default: 100000)
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
        max_result_size: int = DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
        console_capture: bool = True,
        snapshot_between_turns: bool = False,
    ) -> None:
        """Initialize the code interpreter middleware.

        Args:
            config: Soothe configuration. If provided, other args are overridden
                by config.code_interpreter values.
            ptc_allowlist: List of tool names exposed via tools.* namespace.
            memory_limit_mb: Interpreter memory limit in MB (mapped to ``memory_limit`` bytes).
            timeout_seconds: Per-eval timeout in seconds (mapped to ``timeout`` float).
            max_ptc_calls: Maximum programmatic tool calls per eval.
            max_result_size: Maximum result size in characters (mapped to ``max_result_chars``).
            console_capture: Capture console.log output (mapped to ``capture_console``).
            snapshot_between_turns: Preserve state between conversation turns.
        """
        super().__init__()
        # Use config values if provided, otherwise use explicit args
        if config is not None:
            ci_config = config.agent.code_interpreter
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
        self.tools: list[Any] = []

    def _initialize_inner(self) -> AgentMiddleware | None:
        """Initialize the underlying langchain_quickjs CodeInterpreterMiddleware.

        Returns:
            The initialized middleware or None if langchain_quickjs is not available.
        """
        if self._inner_middleware is not None:
            return self._inner_middleware

        try:
            from langchain_quickjs import CodeInterpreterMiddleware as QuickJSMiddleware

            quickjs_kwargs: dict[str, Any] = {
                "ptc": self._ptc_allowlist or None,
                "memory_limit": self._memory_limit_mb * 1024 * 1024,
                "timeout": float(self._timeout_seconds),
                "max_ptc_calls": self._max_ptc_calls,
                "max_result_chars": self._max_result_size,
                "capture_console": self._console_capture,
            }
            if "snapshot_between_turns" in inspect.signature(QuickJSMiddleware).parameters:
                quickjs_kwargs["snapshot_between_turns"] = self._snapshot_between_turns
            self._inner_middleware = QuickJSMiddleware(**quickjs_kwargs)
            self.tools = list(self._inner_middleware.tools)
            self.state_schema = self._inner_middleware.state_schema
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
                "Install with: uv add langchain-quickjs (or upgrade soothe)"
            )
            return None

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Hook called before agent execution."""
        inner = self._initialize_inner()
        if inner is not None:
            return await inner.abefore_agent(state, runtime)
        return None

    async def aafter_agent(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Hook called after agent execution."""
        inner = self._initialize_inner()
        if inner is not None:
            return await inner.aafter_agent(state, runtime)
        return None

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Pass through — QuickJS middleware uses model-call hooks, not tool wrapping."""
        return await handler(request)

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Delegate REPL system prompt and PTC setup to langchain_quickjs."""
        inner = self._initialize_inner()
        if inner is not None:
            return inner.wrap_model_call(request, handler)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Delegate REPL system prompt and PTC setup to langchain_quickjs (async path)."""
        inner = self._initialize_inner()
        if inner is not None:
            return await inner.awrap_model_call(request, handler)
        return await handler(request)
