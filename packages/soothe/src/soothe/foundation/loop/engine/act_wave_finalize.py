"""Act-wave finalize resolution (IG-355, IG-356, IG-357, RFC-227).

This module handles the computation of visible assistant text for Execute waves.
After each Execute wave, adaptive goal completion and headless replay use
``LoopState.last_execute_assistant_text``. That string may come from:

- **root_assistant_stream** — aggregated root-graph ``AIMessage`` / chunk text
- **task_tool_aggregate** — ordered ``task`` ``ToolMessage`` bodies (delegate finals)
- **none** — no usable text (empty wave)

The provenance tracking enables replay systems to correctly identify when
delegate finals should be used vs root assistant stream text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

from soothe.utils.text_preview import preview_first

ActWaveAnswerProvenance = Literal["root_assistant_stream", "task_tool_aggregate", "none"]

# Cap for joined delegate text and for root assistant text stored on state (memory bound).
DELEGATE_FINAL_WAVE_CAP = 120_000

# Char budget for the <LAST_TOOL_RESULT> evidence block used by
# ``_update_prior_progress`` as a fallback when the assistant produced no
# prose text. Plan-assess reads this to grade goal progress on concrete
# tool output rather than only the AI's prose summary.
LAST_TOOL_RESULT_HEAD_CHARS = 500


def _first_arg_head_for_tool_call(call: dict[str, Any]) -> str:
    """Return a compact head string for a single AIMessage tool-call (RFC-227).

    Picks the first non-empty argument value (in declaration order), stringifies
    it on one line, strips, and caps at 120 chars. Returns ``""`` when no usable
    arg exists. Used by ``_update_prior_progress`` to give ``<PRIOR_PROGRESS>``
    a concrete handle on what the LLM asked the tool to do (e.g. the command
    string for ``run_command``, the path for ``read_file``).
    """
    args = call.get("args") or {}
    if not isinstance(args, dict):
        return ""
    for value in args.values():
        if value is None:
            continue
        try:
            text = str(value)
        except Exception:  # noqa: BLE001
            continue
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        if first_line:
            return first_line[:120]
    return ""


def _aggregate_tool_calls_from_step_messages(
    messages: list[BaseMessage],
) -> list[dict[str, Any]]:
    """Aggregate tool calls across streamed AI message chunks (RFC-227).

    The executor's stream collector appends raw ``AIMessageChunk`` deltas to
    ``step_messages`` — each chunk's own ``tool_calls`` is partial: the first
    chunk for a call carries ``name`` with empty ``args``, subsequent chunks
    only carry JSON ``args`` deltas under ``tool_call_chunks``. Reading any
    single chunk's ``.tool_calls`` therefore yields ``name="tool"`` placeholders
    with empty ``args``.

    This aggregator walks the full message list, groups deltas by tool-call id
    (falling back to chunk ``index`` when id is missing), concatenates the
    JSON args string, and resolves to a list of ``{name, args}`` dicts in
    arrival order. Complete ``tool_calls`` on a fully-formed ``AIMessage``
    (non-chunk) are honored verbatim and take precedence when present.
    """
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    # Continuation chunks often omit ``id``; we group them with the prior
    # chunk that shares the same stream ``index`` (OpenAI streaming pattern).
    tid_by_index: dict[int, str] = {}

    for msg in messages:
        # AIMessageChunk: aggregate streaming deltas. Skip Path 2 because
        # AIMessageChunk.tool_calls is a derived view of this chunk's own
        # tool_call_chunks (partial info) that would shadow the aggregated state.
        if isinstance(msg, AIMessageChunk):
            for tcc in getattr(msg, "tool_call_chunks", None) or ():
                if not isinstance(tcc, dict):
                    continue
                tid_raw = tcc.get("id")
                idx_raw = tcc.get("index")
                tid: str
                if tid_raw:
                    tid = str(tid_raw).strip()
                elif idx_raw is not None and idx_raw in tid_by_index:
                    tid = tid_by_index[idx_raw]
                else:
                    tid = f"_idx_{idx_raw}" if idx_raw is not None else f"_pos_{len(order)}"
                if idx_raw is not None and idx_raw not in tid_by_index:
                    tid_by_index[idx_raw] = tid
                if tid not in by_key:
                    order.append(tid)
                    by_key[tid] = {"name": "", "args_str": "", "args": None}
                entry = by_key[tid]
                if tcc.get("name") and not entry["name"]:
                    entry["name"] = str(tcc["name"])
                args_chunk = tcc.get("args")
                if isinstance(args_chunk, str) and args_chunk:
                    entry["args_str"] += args_chunk
            continue

        if not isinstance(msg, AIMessage):
            continue

        # Plain (non-chunk) AIMessage: fully-formed tool_calls take precedence.
        for tc in getattr(msg, "tool_calls", None) or ():
            if not isinstance(tc, dict):
                continue
            tid_raw = tc.get("id")
            tid = str(tid_raw).strip() if tid_raw else f"_full_{len(order)}"
            if tid not in by_key:
                order.append(tid)
                by_key[tid] = {"name": "", "args_str": "", "args": None}
            entry = by_key[tid]
            if tc.get("name"):
                entry["name"] = str(tc["name"])
            args_val = tc.get("args")
            if isinstance(args_val, dict) and args_val:
                entry["args"] = args_val

    out: list[dict[str, Any]] = []
    for tid in order:
        entry = by_key[tid]
        args = entry["args"]
        if not args:
            raw = entry["args_str"]
            if raw:
                try:
                    parsed = json.loads(raw)
                    args = parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    args = {}
            else:
                args = {}
        out.append({"name": entry["name"], "args": args})
    return out


def _last_tool_result_block(messages: list[BaseMessage]) -> str:
    """Return a ``<LAST_TOOL_RESULT>`` evidence block, or ``""`` when none.

    Walks ``messages`` in reverse for the most recent ``ToolMessage`` with
    non-empty text content and emits a CDATA-wrapped head so plan-assess sees
    the actual tool output (counts, listings, paths) in the ledger.
    """
    from soothe.foundation.loop.utils.stream_normalize import extract_text_from_message_content

    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        text = extract_text_from_message_content(getattr(msg, "content", None))
        if not text or not text.strip():
            continue
        name = getattr(msg, "name", None) or "tool"
        head = preview_first(text, LAST_TOOL_RESULT_HEAD_CHARS)
        return (
            f'<LAST_TOOL_RESULT name="{name}" bytes="{len(text)}">\n'
            f"<![CDATA[\n{head}\n]]>\n"
            f"</LAST_TOOL_RESULT>"
        )
    return ""


def _full_tool_output_text(messages: list[BaseMessage]) -> str:
    """Extract full tool output text from ToolMessages (IG-479).

    Ledger must store full content; truncation only happens during projection.
    Walks messages in reverse to get the most recent tool output.

    Returns:
        Full text content of the most recent ToolMessage, or "" if none.
    """
    from soothe.foundation.loop.utils.stream_normalize import extract_text_from_message_content

    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        text = extract_text_from_message_content(getattr(msg, "content", None))
        if text and text.strip():
            return text
    return ""


def _outcome_summary_text(outcome: dict[str, Any] | None) -> str:
    """Normalize ``outcome['output_summary']`` into plain text.

    ``create_output_summary`` returns ``{"first": "...", "last": "..."}``.
    We should surface non-empty parts, but avoid stringifying empty dict payloads
    into evidence like ``"{'first': '', 'last': ''}"``.
    """
    if not isinstance(outcome, dict):
        return ""
    summary = outcome.get("output_summary")
    if summary is None:
        return ""
    if isinstance(summary, str):
        return summary.strip()
    if isinstance(summary, dict):
        first = str(summary.get("first", "") or "").strip()
        last = str(summary.get("last", "") or "").strip()
        if first and last:
            return f"{first}\n...\n{last}"
        return first or last
    return ""


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


__all__ = [
    "ActWaveAnswerProvenance",
    "ActWaveFinalizeSnapshot",
    "compute_act_wave_finalize",
    "DELEGATE_FINAL_WAVE_CAP",
    "_aggregate_tool_calls_from_step_messages",
    "_first_arg_head_for_tool_call",
    "_full_tool_output_text",
    "_last_tool_result_block",
    "_outcome_summary_text",
    "LAST_TOOL_RESULT_HEAD_CHARS",
    "provenance_is_task_delegate",
]
