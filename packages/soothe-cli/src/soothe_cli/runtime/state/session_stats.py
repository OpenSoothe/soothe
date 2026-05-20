"""Lightweight session statistics and token formatting utilities.

This module is intentionally kept free of heavy dependencies (no pydantic, no
config, no widget imports) so that `app.py` can import `SessionStats` and
`format_token_count` at module level without pulling in the full
`textual_adapter` dependency tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SpinnerStatus = str | None
"""Spinner line label, or `None` to hide.

Common values include ``Thinking``, ``Offloading``, ``Writing`` (assistant streaming),
``Tools`` (tool execution), and ``Synthesizing`` (goal-completion stream).
"""


@dataclass
class ModelStats:
    """Token stats for a single model within a session.

    Attributes:
        request_count: Number of LLM API requests made to this model.
        input_tokens: Cumulative input tokens sent to this model.
        output_tokens: Cumulative output tokens received from this model.
    """

    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class SessionStats:
    """Stats accumulated over a single agent turn (or full session).

    Attributes:
        request_count: Total LLM API requests made (each chunk with
            usage_metadata counts as one completed request).
        input_tokens: Cumulative input tokens across all LLM requests.
        output_tokens: Cumulative output tokens across all LLM requests.
        wall_time_seconds: Wall-clock duration from stream start to end.
        per_model: Per-model breakdown keyed by model name.
            Populated only when `record_request` receives a non-empty
            `model_name`. Empty dict means no named-model requests were
            recorded; `print_usage_table` omits the model table in that case and
            shows only the wall-time line (if applicable).
    """

    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_time_seconds: float = 0.0
    per_model: dict[str, ModelStats] = field(default_factory=dict)
    event_stats: TurnEventStats | None = None

    def record_request(
        self,
        model_name: str,
        input_toks: int,
        output_toks: int,
    ) -> None:
        """Accumulate token counts for one completed LLM request.

        Updates both the session totals and the per-model breakdown.

        Args:
            model_name: The model that served this request (used as the
                per-model key). Pass an empty string to skip the per-model
                breakdown for this request.
            input_toks: Input tokens for this request.
            output_toks: Output tokens for this request.
        """
        self.request_count += 1
        self.input_tokens += input_toks
        self.output_tokens += output_toks
        if model_name:
            entry = self.per_model.setdefault(model_name, ModelStats())
            entry.request_count += 1
            entry.input_tokens += input_toks
            entry.output_tokens += output_toks

    def merge(self, other: SessionStats) -> None:
        """Merge another `SessionStats` into this one (mutates *self*).

        Used to accumulate per-turn stats into a session-level total.

        Args:
            other: The stats to fold in.
        """
        self.request_count += other.request_count
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.wall_time_seconds += other.wall_time_seconds
        for model, ms in other.per_model.items():
            entry = self.per_model.setdefault(model, ModelStats())
            entry.request_count += ms.request_count
            entry.input_tokens += ms.input_tokens
            entry.output_tokens += ms.output_tokens
        if other.event_stats is not None:
            if self.event_stats is None:
                self.event_stats = TurnEventStats()
            self.event_stats.merge(other.event_stats)


@dataclass
class TurnEventStats:
    """Event counts accumulated over a single daemon turn.

    Tracks the volume and breakdown of WebSocket chunks received from the
    daemon so that performance anomalies (excessive events, missing modes)
    can be diagnosed from CLI logs.

    Attributes:
        total: Total chunks yielded to the turn loop.
        messages: Chunks with ``mode="messages"``.
        updates: Chunks with ``mode="updates"``.
        custom: Chunks with ``mode="custom"``.
        skipped: Chunks discarded as invalid.
        tool_calls: ``messages`` chunks containing tool-call blocks.
        tool_results: ``messages`` chunks containing tool-result blocks.
        text_chunks: ``messages`` chunks containing assistant text deltas.
        heartbeats_dropped: Heartbeat events silently dropped before yielding.
        post_idle_drained: Chunks received during the post-idle drain window.
    """

    total: int = 0
    messages: int = 0
    updates: int = 0
    custom: int = 0
    skipped: int = 0
    tool_calls: int = 0
    tool_results: int = 0
    text_chunks: int = 0
    heartbeats_dropped: int = 0
    post_idle_drained: int = 0

    def record(
        self,
        mode: str,
        *,
        is_tool_call: bool = False,
        is_tool_result: bool = False,
        is_text: bool = False,
    ) -> None:
        """Increment counters for one received chunk.

        Args:
            mode: Stream mode (``"messages"``, ``"updates"``, or ``"custom"``).
            is_tool_call: Chunk carries at least one tool-call block.
            is_tool_result: Chunk carries at least one tool-result block.
            is_text: Chunk carries assistant text content.
        """
        self.total += 1
        if mode == "messages":
            self.messages += 1
        elif mode == "updates":
            self.updates += 1
        elif mode == "custom":
            self.custom += 1
        if is_tool_call:
            self.tool_calls += 1
        if is_tool_result:
            self.tool_results += 1
        if is_text:
            self.text_chunks += 1

    def merge(self, other: TurnEventStats) -> None:
        """Merge another ``TurnEventStats`` into this one (mutates *self*).

        Args:
            other: The stats to fold in.
        """
        self.total += other.total
        self.messages += other.messages
        self.updates += other.updates
        self.custom += other.custom
        self.skipped += other.skipped
        self.tool_calls += other.tool_calls
        self.tool_results += other.tool_results
        self.text_chunks += other.text_chunks
        self.heartbeats_dropped += other.heartbeats_dropped
        self.post_idle_drained += other.post_idle_drained

    def summary_line(self) -> str:
        """Return a one-line summary suitable for structured logging.

        Returns:
            Compact string like ``847 total (612 msg, 89 upd, 146 custom; …)``.
        """
        parts = [f"{self.total} total"]
        mode_parts = []
        if self.messages:
            mode_parts.append(f"{self.messages} msg")
        if self.updates:
            mode_parts.append(f"{self.updates} upd")
        if self.custom:
            mode_parts.append(f"{self.custom} custom")
        if mode_parts:
            parts.append(f"({', '.join(mode_parts)})")

        detail_parts = []
        if self.tool_calls:
            detail_parts.append(f"{self.tool_calls} tools")
        if self.tool_results:
            detail_parts.append(f"{self.tool_results} results")
        if self.text_chunks:
            detail_parts.append(f"{self.text_chunks} text")
        if self.skipped:
            detail_parts.append(f"{self.skipped} skipped")
        if self.heartbeats_dropped:
            detail_parts.append(f"{self.heartbeats_dropped} hb-drop")
        if self.post_idle_drained:
            detail_parts.append(f"{self.post_idle_drained} post-idle")
        if detail_parts:
            parts.append("; ".join(detail_parts))

        return " ".join(parts)


def format_token_count(count: int) -> str:
    """Format a token count into a human-readable short string.

    Args:
        count: Number of tokens.

    Returns:
        Formatted string like `'12.5K'`, `'1.2M'`, or `'500'`.
    """
    if count >= 1_000_000:  # noqa: PLR2004
        return f"{count / 1_000_000:.1f}M"
    if count >= 1000:  # noqa: PLR2004
        return f"{count / 1000:.1f}K"
    return str(count)
