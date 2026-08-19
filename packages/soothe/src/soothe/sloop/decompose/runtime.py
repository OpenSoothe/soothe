"""Runtime context for executor-bound ``decompose_task`` (RFC-904 / IG-751)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from soothe.context.decomposition import DecompositionProposal

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


@dataclass
class ProposalSink:
    """Mutable queue of proposals for one goal run."""

    proposals: list[DecompositionProposal] = field(default_factory=list)

    def enqueue(self, proposal: DecompositionProposal) -> None:
        self.proposals.append(proposal)

    def drain(self) -> list[DecompositionProposal]:
        out = list(self.proposals)
        self.proposals.clear()
        return out


def bind_decompose_runtime(
    *,
    step_id: str,
    sink: list[DecompositionProposal],
    wave_seq: int = 0,
) -> DecomposeRuntimeTokens:
    """Bind step id + proposal sink for the current CoreAgent turn."""
    return DecomposeRuntimeTokens(
        step=_current_step_id.set(step_id),
        wave=_wave_seq.set(wave_seq),
        sink=_proposal_sink.set(sink),
    )


def reset_decompose_runtime(tokens: DecomposeRuntimeTokens) -> None:
    """Restore prior contextvar values."""
    _current_step_id.reset(tokens.step)
    _wave_seq.reset(tokens.wave)
    _proposal_sink.reset(tokens.sink)


def current_step_id() -> str | None:
    return _current_step_id.get()


def current_wave_seq() -> int:
    return _wave_seq.get()


def current_proposal_sink() -> list[DecompositionProposal] | None:
    return _proposal_sink.get()
