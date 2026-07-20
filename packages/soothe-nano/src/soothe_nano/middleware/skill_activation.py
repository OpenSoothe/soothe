"""RFC-105 / IG-543: Skill discovery, path activation, and body load."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, AgentState, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe_nano.config import SootheConfig
from soothe_nano.skills.index import SkillIndexEntry
from soothe_nano.skills.registry import (
    ProgressiveSkillRegistry,
    merge_skill_activation,
    resolve_core_skill_names,
)
from soothe_nano.skills.search import (
    latest_human_text,
    prefetch_core_skills_from_corpus,
    prefetch_deferred_skills,
    search_deferred_skills,
)

logger = logging.getLogger(__name__)

SEARCH_SKILLS_TOOL = "search_skills"
INVOKE_SKILL_TOOL = "invoke_skill"
SEARCH_TOOLS_TOOL = "search_tools"

FILE_OP_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "delete",
        "insert_lines",
        "apply_diff",
        "file_info",
    }
)
_PATH_KEYS: tuple[str, ...] = ("file_path", "path", "filepath", "file")


class SkillActivationState(AgentState[Any]):
    """Graph state channel for progressive skill disclosure (RFC-105)."""

    skill_activation: NotRequired[Annotated[dict[str, Any], merge_skill_activation]]


class SkillActivationMiddleware(AgentMiddleware):
    """Path activation, search_skills discovery, and invoke_skill body load."""

    state_schema = SkillActivationState

    def __init__(
        self,
        registry: ProgressiveSkillRegistry,
        catalog_provider: Callable[[], Sequence[SkillIndexEntry]],
        config: SootheConfig,
    ) -> None:
        self._registry = registry
        self._catalog_provider = catalog_provider
        self._config = config
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def abefore_agent(self, state, runtime) -> dict | None:
        """Lazy-init ``skill_activation`` and run turn-0 intent prefetch when enabled."""
        if not isinstance(state, dict):
            return None

        changed = False
        activation = state.get("skill_activation")
        if not isinstance(activation, dict):
            activation = ProgressiveSkillRegistry.init_activation_state()
            changed = True

        if await self._maybe_prefetch_intent(state, activation):
            changed = True

        if changed:
            return {
                "skill_activation": ProgressiveSkillRegistry.snapshot_activation_state(activation)
            }
        return None

    async def awrap_tool_call(self, request, handler):
        """Handle skill discovery tools, path activation, or pass through."""
        metadata = getattr(request, "metadata", None) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if metadata.get("_batched"):
            return await handler(request)

        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = str(tool_call.get("name", ""))
        state_raw = getattr(request, "state", None) or {}
        state = state_raw if isinstance(state_raw, dict) else {}

        if tool_name in (
            SEARCH_TOOLS_TOOL,
            SEARCH_SKILLS_TOOL,
        ) and self._has_preloaded_skill_context(state):
            return self._redirect_discovery_when_skill_context_loaded(request, tool_name)

        if tool_name == SEARCH_SKILLS_TOOL:
            return await self._handle_search_skills(request)

        if tool_name == INVOKE_SKILL_TOOL:
            return await self._handle_invoke_skill(request)

        if tool_name not in FILE_OP_TOOLS:
            return await handler(request)

        return await self._handle_file_op(request, handler)

    async def _handle_file_op(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        tool_call = getattr(request, "tool_call", None) or {}
        args = tool_call.get("args", {})
        if not isinstance(args, dict):
            return await handler(request)

        file_paths: list[str] = []
        for key in _PATH_KEYS:
            value = args.get(key)
            if isinstance(value, str):
                file_paths.append(value)
            elif isinstance(value, list):
                file_paths.extend(item for item in value if isinstance(item, str))
        if not file_paths:
            return await handler(request)

        state = getattr(request, "state", None) or {}
        if not isinstance(state, dict):
            return await handler(request)

        activation_state = self._activation(state)
        workspace_raw = state.get("workspace")
        if not workspace_raw:
            return await handler(request)
        workspace = Path(str(workspace_raw))

        all_entries = list(self._catalog_provider())
        core_names = resolve_core_skill_names(self._config.progressive_skills.core_skills)
        _, deferred = self._registry.partition_core_deferred(all_entries, core_names)
        path_skills = self._registry.deferred_with_paths(deferred)
        if not path_skills:
            return await handler(request)

        newly = self._registry.match_paths(activation_state, workspace, file_paths, path_skills)
        if not newly:
            return await handler(request)

        thread_id = str(state.get("thread_id") or state.get("loop_id") or "")
        for skill_name, matched_path, pattern in newly:
            key = (thread_id, skill_name)
            async with await self._lock_for(key):
                if skill_name in activation_state.get("activated", set()):
                    continue
                self._registry.discover(activation_state, [skill_name], via="path")
                try:
                    from soothe_nano.skills.workspace_sync import sync_specific_skill_to_workspace

                    sync_specific_skill_to_workspace(self._config, workspace, skill_name)
                except Exception:  # noqa: BLE001
                    logger.exception("[Skill] sync failed for %s", skill_name)

        state["skill_activation"] = activation_state
        return await handler(request)

    async def _maybe_prefetch_intent(
        self,
        state: dict[str, Any],
        activation_state: dict[str, Any],
    ) -> bool:
        ps = self._config.progressive_skills
        if not ps.intent_prefetch_enabled:
            return False
        if activation_state.get("intent_prefetched"):
            return False

        activation_state["intent_prefetched"] = True
        if ps.intent_prefetch_top_k <= 0:
            return True

        goal = latest_human_text(state)
        if not goal or len(goal) < ps.intent_prefetch_min_query_chars:
            return True

        all_entries = list(self._catalog_provider())
        core_names = resolve_core_skill_names(ps.core_skills)
        core_entries, deferred = self._registry.partition_core_deferred(all_entries, core_names)
        activated = activation_state.get("activated", set())
        if not isinstance(activated, set):
            activated = set(activated)
        invoked = activation_state.get("invoked", set())
        if not isinstance(invoked, set):
            invoked = set(invoked)
        skip_names = activated | invoked

        catalog_by_name = {entry.name: entry for entry in all_entries}

        core_matches: list[SkillIndexEntry] = []
        if ps.core_intent_auto_invoke_enabled and ps.intent_prefetch_top_k > 0:
            core_matches = prefetch_core_skills_from_corpus(
                goal,
                core_entries,
                discovered=skip_names,
                limit=ps.intent_prefetch_top_k,
                registry=self._registry,
            )
            if core_matches:
                workspace_raw = state.get("workspace")
                workspace = str(workspace_raw) if workspace_raw else None
                loaded = self._auto_invoke_core_skills(
                    activation_state,
                    core_matches,
                    workspace=workspace,
                )
                if loaded:
                    logger.debug("[Skill] core intent auto-invoked %s", loaded)

        if not core_matches:
            matches = await prefetch_deferred_skills(
                goal,
                deferred,
                discovered=skip_names,
                limit=ps.intent_prefetch_top_k,
                registry=self._registry,
                config=self._config,
                catalog_by_name=catalog_by_name,
            )
            if matches:
                self._registry.discover(
                    activation_state,
                    [entry.name for entry in matches],
                    via="search",
                )
                logger.debug(
                    "[Skill] intent prefetch discovered deferred %s",
                    [entry.name for entry in matches],
                )
        return True

    def _auto_invoke_core_skills(
        self,
        activation_state: dict[str, Any],
        entries: Sequence[SkillIndexEntry],
        *,
        workspace: str | None,
    ) -> list[str]:
        """Load matched core skill bodies into ``skill_activation`` on turn 0."""
        loaded: list[str] = []
        for entry in entries:
            resolved = self._invoke_skill_into_activation(
                activation_state,
                entry.name,
                workspace=workspace,
                preload=True,
            )
            if resolved:
                loaded.append(resolved)
        return loaded

    def _invoke_skill_into_activation(
        self,
        activation_state: dict[str, Any],
        name: str,
        *,
        workspace: str | None,
        preload: bool = False,
    ) -> str | None:
        """Read SKILL.md and mark a skill invoked. Returns resolved name or None."""
        from soothe_nano.skills.catalog import (
            build_skill_context_text,
            read_skill_markdown,
            resolve_skill_directory,
        )

        meta = resolve_skill_directory(self._config, name, workspace)
        if meta is None:
            return None
        markdown = read_skill_markdown(meta)
        if not markdown:
            return None
        resolved_name = str(meta.get("name") or name)
        body = build_skill_context_text(meta, markdown)
        self._registry.discover(activation_state, [resolved_name], via="explicit")
        if preload:
            self._registry.mark_preloaded(activation_state, resolved_name, body)
        else:
            self._registry.mark_invoked(activation_state, resolved_name, body)
        return resolved_name

    @staticmethod
    def _has_preloaded_skill_context(state: dict[str, Any]) -> bool:
        """True when turn-0 preload or invoke loaded skill bodies into the prompt."""
        activation = state.get("skill_activation")
        if not isinstance(activation, dict):
            return False
        bodies = activation.get("invoked_bodies") or {}
        return bool(bodies)

    def _redirect_discovery_when_skill_context_loaded(
        self,
        request: ToolCallRequest,
        tool_name: str,
    ) -> Command[Any]:
        """Short-circuit deferred discovery tools when SKILL_CONTEXT is already active."""
        tool_call = getattr(request, "tool_call", None) or {}
        state_raw = getattr(request, "state", None) or {}
        activation_state = self._activation(state_raw if isinstance(state_raw, dict) else {})
        tool_call_id = str(tool_call.get("id", "") or tool_call.get("tool_call_id", ""))
        content = (
            "Skill instructions are already loaded in SKILL_CONTEXT for this thread. "
            "Follow them directly (e.g. run_command or run_python). "
            f"{tool_name} only discovers deferred tools/skills and cannot replace pre-loaded skill guidance."
        )
        message = ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_name)
        return self._command_with_activation(message, activation_state)

    async def _handle_search_skills(self, request: ToolCallRequest) -> Command[Any]:
        tool_call = getattr(request, "tool_call", None) or {}
        args = tool_call.get("args", {})
        if not isinstance(args, dict):
            args = {}
        query = str(args.get("query", ""))
        limit = int(args.get("limit", 5) or 5)

        state = getattr(request, "state", None) or {}
        activation_state = self._activation(state if isinstance(state, dict) else {})

        all_entries = list(self._catalog_provider())
        core_names = resolve_core_skill_names(self._config.progressive_skills.core_skills)
        _, deferred = self._registry.partition_core_deferred(all_entries, core_names)
        discovered = activation_state.get("activated", set())
        if not isinstance(discovered, set):
            discovered = set(discovered)

        matches = await search_deferred_skills(
            query,
            deferred,
            discovered=discovered,
            limit=limit,
            registry=self._registry,
            config=self._config,
            catalog_by_name={entry.name: entry for entry in all_entries},
        )
        if not matches:
            content = f"No deferred skills matched query={query!r}."
        else:
            self._registry.discover(
                activation_state,
                [entry.name for entry in matches],
                via="search",
            )
            lines = [f"- {entry.name}: {entry.description}" for entry in matches]
            content = (
                f"Discovered {len(matches)} skill(s) for this thread:\n"
                + "\n".join(lines)
                + "\nMetadata appears on the next model hop. "
                "Call invoke_skill(name) to load full instructions."
            )

        if isinstance(state, dict):
            state["skill_activation"] = activation_state

        tool_call_id = str(tool_call.get("id", "") or tool_call.get("tool_call_id", ""))
        message = ToolMessage(content=content, tool_call_id=tool_call_id, name=SEARCH_SKILLS_TOOL)
        return self._command_with_activation(message, activation_state)

    async def _handle_invoke_skill(self, request: ToolCallRequest) -> Command[Any]:
        tool_call = getattr(request, "tool_call", None) or {}
        args = tool_call.get("args", {})
        if not isinstance(args, dict):
            args = {}
        name = str(args.get("name", "")).strip()
        user_args = str(args.get("args", "") or "")

        state = getattr(request, "state", None) or {}
        activation_state = self._activation(state if isinstance(state, dict) else {})
        workspace_raw = state.get("workspace") if isinstance(state, dict) else None
        workspace = str(workspace_raw) if workspace_raw else None

        tool_call_id = str(tool_call.get("id", "") or tool_call.get("tool_call_id", ""))

        if not name:
            message = ToolMessage(
                content="invoke_skill requires a non-empty name.",
                tool_call_id=tool_call_id,
                name=INVOKE_SKILL_TOOL,
            )
            return self._command_with_activation(message, activation_state)

        resolved_name = self._invoke_skill_into_activation(
            activation_state,
            name,
            workspace=workspace,
        )
        if resolved_name is None:
            message = ToolMessage(
                content=f"Skill not found: {name!r}. Try search_skills(query) first.",
                tool_call_id=tool_call_id,
                name=INVOKE_SKILL_TOOL,
            )
            return self._command_with_activation(message, activation_state)

        if isinstance(state, dict):
            state["skill_activation"] = activation_state

        preview = user_args.strip()
        if preview:
            content = (
                f"Loaded skill {resolved_name!r}. User instruction: {preview}\n"
                "Full skill reference will appear in SKILL_CONTEXT on subsequent hops."
            )
        else:
            content = (
                f"Loaded skill {resolved_name!r}. "
                "Full skill reference will appear in SKILL_CONTEXT on subsequent hops."
            )
        message = ToolMessage(content=content, tool_call_id=tool_call_id, name=INVOKE_SKILL_TOOL)
        return self._command_with_activation(message, activation_state)

    @staticmethod
    def _activation(state: dict[str, Any]) -> dict[str, Any]:
        activation = state.get("skill_activation")
        if not isinstance(activation, dict):
            activation = ProgressiveSkillRegistry.init_activation_state()
            state["skill_activation"] = activation
        return activation

    @staticmethod
    def _command_with_activation(
        result: ToolMessage,
        activation_state: dict[str, Any],
    ) -> Command[Any]:
        return Command(
            update={
                "skill_activation": ProgressiveSkillRegistry.snapshot_activation_state(
                    activation_state
                ),
                "messages": [result],
            }
        )

    async def _lock_for(self, key: tuple[str, str]) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock
