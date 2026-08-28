"""Runtime context for executor-bound ``decompose_task``."""

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
# Count of evidence-gathering tool calls (ls/glob/grep/read_file/...) made
# in the current step thread before a decompose_task call. Used by the
# decompose tool handler's evidence-call gate to reject proposals issued
# with zero prior grounding (d15f hallucination defense, scheme 2d).
#
# Stored as a single-element list, not an int: LangGraph's Pregel executor
# runs each graph node inside a ``copy_context()`` snapshot (pregel/_executor.py).
# ``ContextVar.set`` writes are copy-on-write — an ``int`` increment made inside
# the ToolNode's snapshot never reaches the parent context or the snapshot that
# runs ``decompose_task`` in a later turn, so the gate always sees 0 (loop 7e83 /
# 48bd: every decompose_task rejected as "no prior evidence" despite dozens of
# ls/grep/read_file calls). A mutable container is *referenced* (not copied) by
# ``copy_context()``, so in-place mutation of the list is visible across every
# snapshot that shares the reference bound at ``bind_decompose_runtime``.
_evidence_calls: ContextVar[list[int]] = ContextVar("decompose_evidence_calls", default=None)

# Accumulated excerpts of grounding-tool *outputs* (ToolMessage content) in
# the current step thread. Fed to the LLM grounding critic in
# ``grounding_guard.check_proposal_grounded`` so it can judge whether a
# decompose proposal's claims are backed by evidence the model actually saw
# — without touching the filesystem (sandbox-compatible). Same mutable-list
# pattern as ``_evidence_calls``: a list is *referenced* (not copied) by
# LangGraph's ``copy_context()`` snapshots, so in-place appends are visible
# across every snapshot that shares the reference bound at
# ``bind_decompose_runtime``.
_EVIDENCE_EXCERPT_CAP = 2000  # per-entry char cap (bounds memory)
_evidence_corpus: ContextVar[list[str] | None] = ContextVar(
    "decompose_evidence_corpus", default=None
)


def _evidence_counter() -> list[int]:
    """Return the bound evidence counter list, binding a fresh one if absent.

    The default ``None`` token means "not yet bound for this step"; the first
    access (from either the middleware recorder or the gate reader) lazily
    binds a shared list so the same object reference is seen across
    ``copy_context()`` snapshots regardless of which side touches it first.
    """
    lst = _evidence_calls.get()
    if lst is None:
        lst = [0]
        _evidence_calls.set(lst)
    return lst


@dataclass
class DecomposeRuntimeTokens:
    """Tokens to reset after a step thread finishes."""

    step: Token[str | None]
    wave: Token[int]
    sink: Token[list[DecompositionProposal] | None]
    evidence: Token[list[int] | None]
    evidence_corpus: Token[list[str] | None]


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
        evidence=_evidence_calls.set([0]),
        evidence_corpus=_evidence_corpus.set([]),
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
    _evidence_calls.reset(tokens.evidence)
    _evidence_corpus.reset(tokens.evidence_corpus)


def current_step_id() -> str | None:
    return _current_step_id.get()


def current_wave_seq() -> int:
    return _wave_seq.get()


def current_proposal_sink() -> list[DecompositionProposal] | None:
    return _proposal_sink.get()


def current_evidence_calls() -> int:
    """Return the count of evidence-gathering tool calls in this step thread."""
    return _evidence_counter()[0]


def record_evidence_call() -> None:
    """Increment the evidence-gathering call counter for this step thread."""
    _evidence_counter()[0] += 1


def _evidence_corpus_list() -> list[str]:
    """Return the bound evidence-corpus list, binding a fresh one if absent.

    Lazy-binds a shared list (same copy_context-safe pattern as
    ``_evidence_counter``) so appends made inside a Pregel ``copy_context()``
    snapshot are visible to the snapshot that runs ``decompose_task``.
    """
    lst = _evidence_corpus.get()
    if lst is None:
        lst = []
        _evidence_corpus.set(lst)
    return lst


def record_evidence_output(text: str) -> None:
    """Append a truncated excerpt of a grounding-tool output to the corpus.

    Called by ``DecomposeTaskMiddleware`` after each grounding tool runs.
    Per-entry cap bounds memory; the critic prompt also caps the total.
    """
    excerpt = (text or "").strip()
    if not excerpt:
        return
    if len(excerpt) > _EVIDENCE_EXCERPT_CAP:
        excerpt = excerpt[: _EVIDENCE_EXCERPT_CAP - 1] + "…"
    _evidence_corpus_list().append(excerpt)


def current_evidence_corpus() -> list[str]:
    """Return the accumulated evidence excerpts for this step thread."""
    return _evidence_corpus_list()


def langgraph_configurable() -> dict[str, Any]:
    """Return the LangGraph ``configurable`` dict for the current task context.

    Shared by the decompose middleware and tool handler to read workspace /
    step-binding keys without duplicating the ``get_config`` boilerplate.
    Returns ``{}`` when no LangGraph runtime context is active.
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
