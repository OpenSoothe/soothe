"""Runtime context for executor-bound `decompose_task`."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from soothe.context.decomposition import DecompositionProposal

logger = logging.getLogger(__name__)

_current_step_id: ContextVar[str | None] = ContextVar("decompose_step_id", default=None)
_wave_seq: ContextVar[int] = ContextVar("decompose_wave_seq", default=0)
_proposal_sink: ContextVar[list[DecompositionProposal] | None] = ContextVar(
    "decompose_proposal_sink", default=None
)


@dataclass
class DecomposeRuntimeTokens:
    """Tokens to reset after a step thread finishes."""

    step: Token[str | None]
    wave: Token[int]
    sink: Token[list[DecompositionProposal] | None]


def bind_decompose_runtime(
    *,
    step_id: str,
    sink: list[DecompositionProposal],
    wave_seq: int = 0,
) -> DecomposeRuntimeTokens:
    """Bind step id + proposal sink for the current CoreAgent turn."""
    logger.debug(
        "[decompose] bind runtime step=%s wave=%d sink_id=%d sink_bound=%s",
        step_id,
        wave_seq,
        id(sink),
        sink is not None,
    )
    return DecomposeRuntimeTokens(
        step=_current_step_id.set(step_id),
        wave=_wave_seq.set(wave_seq),
        sink=_proposal_sink.set(sink),
    )


def reset_decompose_runtime(tokens: DecomposeRuntimeTokens) -> None:
    """Restore prior contextvar values."""
    step_id = _current_step_id.get()
    sink = _proposal_sink.get()
    queued = len(sink) if sink else 0
    logger.debug("[decompose] reset runtime step=%s proposals_queued=%d", step_id, queued)
    _current_step_id.reset(tokens.step)
    _wave_seq.reset(tokens.wave)
    _proposal_sink.reset(tokens.sink)


def current_step_id() -> str | None:
    return _current_step_id.get()


def current_wave_seq() -> int:
    return _wave_seq.get()


def current_proposal_sink() -> list[DecompositionProposal] | None:
    return _proposal_sink.get()


def langgraph_configurable() -> dict[str, Any]:
    """Return the LangGraph `configurable` dict for the current task context.

    Shared by the decompose middleware and tool handler to read workspace /
    step-binding keys without duplicating the `get_config` boilerplate.
    Returns `{}` when no LangGraph runtime context is active.
    """
    try:
        from langgraph.config import get_config

        lg_cfg = get_config()
    except Exception:
        return {}
    if not isinstance(lg_cfg, dict):
        return {}
    conf = lg_cfg.get("configurable")
    return conf if isinstance(conf, dict) else {}
