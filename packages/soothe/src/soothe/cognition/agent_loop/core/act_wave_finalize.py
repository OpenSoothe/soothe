"""Act-wave visible answer: single resolution model for finalize / goal-completion wiring.

After each Execute wave, adaptive goal completion and headless replay use
``LoopState.last_execute_assistant_text``. That string may come from:

- **root_assistant_stream** — aggregated root-graph ``AIMessage`` / chunk text (same path as act
  aggregation for the main graph).
- **task_tool_aggregate** — ordered ``task`` ``ToolMessage`` bodies (delegate finals), including
  parallel waves merged with ``\\n\\n---\\n\\n`` (IG-356).
- **none** — no usable text (empty wave).

``last_wave_answer_from_delegate_final`` on ``LoopState`` remains the boolean hook for runner
replay (IG-355); it is True iff provenance is ``task_tool_aggregate``.

See IG-355, IG-356, IG-357.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ActWaveAnswerProvenance = Literal["root_assistant_stream", "task_tool_aggregate", "none"]

# Cap for joined delegate text and for root assistant text stored on state (memory bound).
DELEGATE_FINAL_WAVE_CAP = 120_000


@dataclass(frozen=True, slots=True)
class ActWaveFinalizeSnapshot:
    """Resolved user-visible text for the last Execute wave and how it was obtained."""

    visible_text: str | None
    provenance: ActWaveAnswerProvenance


def compute_act_wave_finalize(
    *,
    parallel_multi_step: bool,
    root_assistant_text: str,
    delegate_final_text: str | None,
    wave_text_cap: int = DELEGATE_FINAL_WAVE_CAP,
) -> ActWaveFinalizeSnapshot:
    """Compute visible assistant text and provenance for one Execute wave.

    Args:
        parallel_multi_step: Whether this wave ran multiple parallel steps.
        root_assistant_text: Pre-aggregated root-graph assistant text (ignored when
            ``parallel_multi_step`` is True except conceptually empty).
        delegate_final_text: Joined ``task`` tool return bodies for this wave, if any.
        wave_text_cap: Maximum stored length for delegate (and enforced consistently upstream).

    Returns:
        Snapshot with trimmed ``visible_text`` and ``provenance``.
    """
    delegate = (delegate_final_text or "").strip()
    if parallel_multi_step:
        if delegate:
            text = delegate[:wave_text_cap] if len(delegate) > wave_text_cap else delegate
            return ActWaveFinalizeSnapshot(text, "task_tool_aggregate")
        return ActWaveFinalizeSnapshot(None, "none")

    if delegate:
        text = delegate[:wave_text_cap] if len(delegate) > wave_text_cap else delegate
        return ActWaveFinalizeSnapshot(text, "task_tool_aggregate")

    root = root_assistant_text.strip()
    if root:
        return ActWaveFinalizeSnapshot(root, "root_assistant_stream")
    return ActWaveFinalizeSnapshot(None, "none")


def provenance_is_task_delegate(snapshot: ActWaveFinalizeSnapshot) -> bool:
    """True when visible text came from ``task`` tool returns (delegate finals)."""
    return snapshot.provenance == "task_tool_aggregate"
