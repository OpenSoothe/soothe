"""WestWorldMiddleware: fixed directive phrase → fixed agent behavior."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.prompts import WESTWORLD_FANOUT_ADDENDUM
from soothe.sloop.decompose import runtime as _decompose_runtime
from soothe.sloop.utils.config_keys import (
    SOOTHE_DECOMPOSE_STEP_ID_KEY,
    SOOTHE_EVAL_STEP_ID_KEY,
    SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY,
    SOOTHE_INTERACTION_MODE_KEY,
)

logger = logging.getLogger(__name__)

# ── Trigger registry ──────────────────────────────────────────────────────
# Each entry: (phrase, addendum). Phrase match is case-insensitive substring
# against the last HumanMessage content. Add new phrases here.
_WESTWORLD_TRIGGERS: list[tuple[str, str]] = [
    ("fan out beams", WESTWORLD_FANOUT_ADDENDUM),
    ("fan out subagents", WESTWORLD_FANOUT_ADDENDUM),
]


def _last_human_text(request: ModelRequest[ContextT]) -> str:
    """Return the text content of the last `HumanMessage` in the request.

    The last HumanMessage is the current step envelope (root = user goal text,
    child = child task description). Scanning only it prevents a phrase in a
    projected root envelope from re-triggering fan-out on every child thread.
    Returns `""` when there is no HumanMessage or content is non-textual.
    """
    messages = list(request.messages or [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Concatenate text blocks; ignore non-text blocks (images etc.)
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and "text" in block
                ]
                return "\n".join(p for p in parts if p)
            return ""
    return ""


def _match_triggers(text: str) -> list[str]:
    """Return addenda for every phrase (case-insensitive) present in `text`."""
    if not text:
        return []
    lowered = text.lower()
    return [addendum for phrase, addendum in _WESTWORLD_TRIGGERS if phrase in lowered]


def _append_addenda(
    request: ModelRequest[ContextT],
    addenda: list[str],
) -> ModelRequest[ContextT]:
    """Append trigger addenda to the system message (str + list content, idempotent)."""
    if not addenda:
        return request
    system = request.system_message
    if system is None or not hasattr(system, "content"):
        return request
    content = system.content
    combined = "\n\n".join(addenda)
    if isinstance(content, str):
        if combined in content:
            return request
        return request.override(system_message=SystemMessage(content=f"{content}\n\n{combined}"))
    if isinstance(content, list):
        # Idempotent: skip if the full combined block is already present.
        existing_text = "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and "text" in block
        )
        if combined in existing_text:
            return request
        new_blocks = [*content, {"type": "text", "text": f"\n\n{combined}"}]
        return request.override(system_message=SystemMessage(content=new_blocks))
    return request


class WestWorldMiddleware(AgentMiddleware):
    """Inject directive-phrase addenda that override agent behavior.

    Active on real agent-mode step threads (where `decompose_task` exists).
    Inert everywhere else (plan/ask modes strip the tool; eval and
    goal-synthesis have their own policies; non-step threads have no step id).
    """

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        conf = _decompose_runtime.langgraph_configurable()
        # Guard: only on a real decompose step thread.
        step_id = _decompose_runtime.current_step_id() or conf.get(SOOTHE_DECOMPOSE_STEP_ID_KEY)
        if not step_id:
            return request
        # Guard: skip modes/policies where decompose_task is unavailable.
        if conf.get(SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY):
            return request
        if conf.get(SOOTHE_EVAL_STEP_ID_KEY):
            return request
        mode = conf.get(SOOTHE_INTERACTION_MODE_KEY)
        if mode in ("plan", "ask"):
            return request
        # Trigger: last HumanMessage only (prevents child-thread recursion).
        addenda = _match_triggers(_last_human_text(request))
        if not addenda:
            return request

        logger.info(
            "[westworld] phrase trigger fired on step %s (mode=%s addenda=%d)",
            step_id,
            mode or "agent",
            len(addenda),
        )
        return _append_addenda(request, addenda)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Apply trigger addenda before the sync model call."""
        return handler(self.modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Apply trigger addenda before the async model call."""
        return await handler(self.modify_request(request))


__all__ = ["WestWorldMiddleware"]
