"""WestWorldMiddleware: fixed directive phrase → fixed agent behavior.

Themed after *Westworld* — narrative triggers that override agent behavior.
When the user's submission contains a registered phrase (e.g. "fan out beams"
or "fan out subagents"), the matching system-prompt addendum is injected so
the model performs a deterministic action.

The registry is extensible: each ``(phrase, addendum)`` pair is one trigger.
The ``fan out beams`` and ``fan out subagents`` triggers ship initially, both
driving the model to call ``decompose_task`` with maximum parallelism
(independent subtasks, zero ``depends_on_local`` edges).

Compatibility with ``DecomposeTaskMiddleware``:
- This middleware only appends a system addendum; it never touches the tool
  list. ``DecomposeTaskMiddleware`` (same suffix, runs after this one) owns
  ``decompose_task`` injection / mode-based stripping.
- Guard conditions mirror ``DecomposeTaskMiddleware`` so the addendum only
  lands on real agent-mode step threads where ``decompose_task`` is present.
- Trigger detection reads only the **last** ``HumanMessage`` (the current
  step envelope), NOT the full projected history. The root envelope carries
  the user goal text (and thus the phrase); child-step envelopes carry the
  child task description (no phrase) — so fan-out fires once at the root and
  does not recurse into children.
"""

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

from soothe.prompts import WESTWORLD_ESCALATION_ADDENDUM, WESTWORLD_FANOUT_ADDENDUM
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

# After this many evidence-gathering calls without a decompose_task proposal
# queued, switch from the fan-out addendum to the escalation addendum (a85d:
# 666 read-only calls stuck in evidence-gathering). The executor's read-only
# streak circuit breaker is the hard stop; this is the soft nudge that fires
# earlier to redirect the model.
_WESTWORLD_ESCALATION_EVIDENCE_THRESHOLD = 10


def _last_human_text(request: ModelRequest[ContextT]) -> str:
    """Return the text content of the last ``HumanMessage`` in the request.

    The last HumanMessage is the current step envelope (root = user goal text,
    child = child task description). Scanning only it prevents a phrase in a
    projected root envelope from re-triggering fan-out on every child thread.
    Returns ``""`` when there is no HumanMessage or content is non-textual.
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
    """Return addenda for every phrase (case-insensitive) present in ``text``."""
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

    Active on real agent-mode step threads (where ``decompose_task`` exists).
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

        # ── Escalation (a85d: evidence-gathering loop) ──────────────────
        # After enough evidence calls without a decompose proposal queued,
        # the model is stuck gathering. Replace the fan-out addendum with
        # the escalation addendum that forces a decision: decompose NOW or
        # execute directly.
        evidence_calls = _decompose_runtime.current_evidence_calls()
        proposal_sink = _decompose_runtime.current_proposal_sink()
        proposals_queued = len(proposal_sink) if proposal_sink else 0
        if (
            evidence_calls >= _WESTWORLD_ESCALATION_EVIDENCE_THRESHOLD
            and proposals_queued == 0
        ):
            logger.info(
                "[westworld] escalation on step %s (mode=%s evidence_calls=%d "
                "proposals_queued=0) — switching to escalation addendum",
                step_id,
                mode or "agent",
                evidence_calls,
            )
            return _append_addenda(request, [WESTWORLD_ESCALATION_ADDENDUM])

        logger.info(
            "[westworld] phrase trigger fired on step %s (mode=%s addenda=%d "
            "evidence_calls=%d)",
            step_id,
            mode or "agent",
            len(addenda),
            evidence_calls,
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
