"""Prepare progressive listing blocks for system-prompt assembly.

Separates listing state transitions from prompt assembly:
- builtin deferred tools -> `<AVAILABLE_TOOLS>`
- progressive skills -> `<AVAILABLE_SKILLS>` and `<SKILL_CONTEXT ...>`
- deferred MCP tools -> `<AVAILABLE_MCP_TOOLS>`
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse

from soothe_nano.config.middleware_access import agent_middleware_config

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


class ProgressiveListingMiddleware(AgentMiddleware):
    """Compute and stash progressive listing blocks into request state."""

    def __init__(
        self,
        config: SootheConfig,
        *,
        mcp_registry: Any | None = None,
        progressive_tool_middleware: Any | None = None,
    ) -> None:
        self._config = config
        self._mcp_registry = mcp_registry
        self._progressive_tool_middleware = progressive_tool_middleware
        # Cache SkillIndex/ProgressiveSkillRegistry across hops.
        self._skill_index: Any = None
        self._skill_registry: Any = None

    def _compose_skills_block(self, state: dict[str, Any] | None) -> tuple[str | None, list[str]]:
        if not state:
            return None, []
        activation = state.get("skill_activation")
        if not isinstance(activation, dict):
            return None, []

        activation.setdefault("sent", set())
        activated = activation.get("activated", set())
        invoked = activation.get("invoked", set())
        just_invoked = activation.get("just_invoked", set())
        bodies = activation.get("invoked_bodies", {})

        if self._skill_index is None:
            from soothe_nano.skills.index import SkillIndex

            self._skill_index = SkillIndex()
        if self._skill_registry is None:
            from soothe_nano.skills.registry import (
                ProgressiveSkillRegistry,
                resolve_core_skill_names,
            )

            self._skill_registry = ProgressiveSkillRegistry()
        else:
            from soothe_nano.skills.registry import resolve_core_skill_names

        entries = self._skill_index.rebuild_if_stale()
        core_names = resolve_core_skill_names(self._config.progressive_skills.core_skills)
        core_entries, _deferred = self._skill_registry.partition_core_deferred(entries, core_names)
        activated_entries = [entry for entry in entries if entry.name in activated]
        by_name = {entry.name: entry for entry in core_entries}
        by_name.update({entry.name: entry for entry in activated_entries})
        candidates = sorted(by_name.values(), key=lambda entry: entry.name.lower())

        new_entries = self._skill_registry.new_for_thread(activation, candidates)

        available_block: str | None = None
        if new_entries:
            listing_entries = [e for e in new_entries if e.name not in just_invoked]

            ctx_limit = int(agent_middleware_config(self._config).context_window_limit)
            budget_pct = float(self._config.progressive_skills.budget_pct)
            budget_chars = max(0, int(ctx_limit * budget_pct))
            per_entry_cap = int(self._config.progressive_skills.max_listing_chars_per_entry)
            min_per_entry = int(self._config.progressive_skills.min_listing_chars_per_entry)

            if listing_entries:
                from soothe_nano.skills.budget import format_skills_within_budget

                text, _telemetry = format_skills_within_budget(
                    listing_entries,
                    budget_chars=budget_chars,
                    per_entry_cap_chars=per_entry_cap,
                    min_per_entry_chars=min_per_entry,
                )
                if text:
                    available_block = f"<AVAILABLE_SKILLS>\n{text}\n</AVAILABLE_SKILLS>"

            self._skill_registry.mark_sent(activation, [e.name for e in new_entries])

        skill_context_blocks: list[str] = []
        for name in sorted(invoked - just_invoked):
            body = bodies.get(name)
            if not body:
                continue
            skill_context_blocks.append(f'<SKILL_CONTEXT name="{name}">\n{body}\n</SKILL_CONTEXT>')

        activation["just_invoked"] = set()
        state["skill_activation"] = activation

        return available_block, skill_context_blocks

    def _compose_mcp_tools_block(self, state: dict[str, Any] | None) -> str | None:
        if not self._mcp_registry or not state:
            return None

        from soothe_nano.mcp.mcp_progressive import ProgressiveMCPRegistry
        from soothe_nano.middleware.mcp_activation import stash_mcp_activation_update

        core_names = frozenset(
            t.name for t in self._mcp_registry.always_loaded_tools() if getattr(t, "name", None)
        )
        progressive = ProgressiveMCPRegistry(always_loaded_names=core_names)

        activation = state.get("mcp_activation")
        if not isinstance(activation, dict):
            activation = ProgressiveMCPRegistry.init_activation_state()
            state["mcp_activation"] = activation

        descriptors = self._mcp_registry.deferred_tools()
        if not descriptors:
            return None

        new_descriptors = progressive.new_for_thread(activation, descriptors)
        if not new_descriptors:
            return None

        ctx_limit = int(agent_middleware_config(self._config).context_window_limit)
        budget_pct = (
            float(self._config.progressive_mcp.budget_pct) if self._config.progressive_mcp else 0.02
        )
        budget_chars = max(0, int(ctx_limit * budget_pct))
        per_entry_cap = (
            int(self._config.progressive_mcp.max_listing_chars_per_entry)
            if self._config.progressive_mcp
            else 250
        )
        min_per_entry = (
            int(self._config.progressive_mcp.min_listing_chars_per_entry)
            if self._config.progressive_mcp
            else 20
        )

        from soothe_nano.mcp.mcp_utils import format_mcp_tools_within_budget

        text, _telemetry = format_mcp_tools_within_budget(
            new_descriptors,
            budget_chars=budget_chars,
            per_entry_cap_chars=per_entry_cap,
            min_per_entry_chars=min_per_entry,
        )
        if not text:
            return None

        progressive.mark_sent(activation, [d.name for d in new_descriptors])
        state["mcp_activation"] = activation
        stash_mcp_activation_update(activation)

        return f"<AVAILABLE_MCP_TOOLS>\n{text}\n</AVAILABLE_MCP_TOOLS>"

    def _compose_available_tools_block(
        self,
        state: dict[str, Any] | None,
        deferred_tools: list[Any] | None,
    ) -> str | None:
        if not self._config.progressive_tools.enabled or not state:
            return None

        from soothe_nano.toolkits.progressive.budget import format_tools_within_budget
        from soothe_nano.toolkits.progressive.registry import ProgressiveToolRegistry

        pt = self._config.progressive_tools
        core = list(pt.core_tools) if pt.core_tools else None
        if pt.search_tools_enabled:
            if core is None:
                from soothe_nano.toolkits.progressive.registry import DEFAULT_CORE_TOOL_NAMES

                core = list(DEFAULT_CORE_TOOL_NAMES)
            elif "search_tools" not in core:
                core.append("search_tools")
        registry = ProgressiveToolRegistry(core_tools=core)

        if deferred_tools is None:
            return None

        descriptors = registry.descriptors_from_tools(deferred_tools)
        _, deferred = registry.partition(descriptors)
        if not deferred:
            return None

        activation = state.get("tool_activation")
        if not isinstance(activation, dict):
            activation = ProgressiveToolRegistry.init_activation_state()
            state["tool_activation"] = activation

        new_entries = registry.new_for_thread(activation, deferred)
        if not new_entries:
            return None

        ctx_limit = int(agent_middleware_config(self._config).context_window_limit)
        budget_chars = max(0, int(ctx_limit * float(pt.budget_pct)))
        text, _telemetry = format_tools_within_budget(
            new_entries,
            budget_chars=budget_chars,
            per_entry_cap_chars=int(pt.max_listing_chars_per_entry),
            min_per_entry_chars=int(pt.min_listing_chars_per_entry),
            include_preamble=True,
        )
        if not text:
            return None

        registry.mark_sent(activation, [e.name for e in new_entries])
        state["tool_activation"] = activation
        from soothe_nano.middleware.progressive_tools import stash_tool_activation_update

        stash_tool_activation_update(activation)
        return f"<AVAILABLE_TOOLS>\n{text}\n</AVAILABLE_TOOLS>"

    def _prepare_listings(self, request: ModelRequest[ContextT]) -> None:
        if not hasattr(request.state, "get"):
            return
        state: dict[str, Any] = request.state

        listing_tools: list[Any] = getattr(request, "tools", None) or []
        if self._progressive_tool_middleware is not None:
            full_catalog = self._progressive_tool_middleware.full_tools_for_listing()
            if full_catalog:
                listing_tools = full_catalog

        tools_block = self._compose_available_tools_block(state, deferred_tools=listing_tools)
        if tools_block:
            state["_available_tools_block"] = tools_block
        else:
            state.pop("_available_tools_block", None)

        skills_block, skill_ctx_blocks = self._compose_skills_block(state)
        if skills_block:
            state["_available_skills_block"] = skills_block
        else:
            state.pop("_available_skills_block", None)
        state["_skill_context_blocks"] = skill_ctx_blocks

        mcp_block = self._compose_mcp_tools_block(state)
        if mcp_block:
            state["_available_mcp_tools_block"] = mcp_block
        else:
            state.pop("_available_mcp_tools_block", None)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Any,
    ) -> ModelResponse[Any]:
        self._prepare_listings(request)
        return handler(request)

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Prepare listing blocks for middleware stacks using `modify_request`."""
        self._prepare_listings(request)
        return request

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Any,
    ) -> ModelResponse[Any]:
        self._prepare_listings(request)
        return await handler(request)
