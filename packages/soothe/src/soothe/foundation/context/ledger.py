"""Ledger manager for the Context Engine (RFC-624)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_DESC_INLINE_MAX = 160
_ERR_INLINE_MAX = 500
_INLINE_SUCCESS_BODY_CAP = 800


@dataclass
class _LedgerEntry:
    """Internal tagged ledger entry."""

    message: BaseMessage
    phase: str | None = None


@dataclass
class LedgerManager:
    """Manages the loop message ledger with phase tagging and compaction.

    Replaces ``LoopWorkingMemory`` and the ``loop_messages`` list from
    StrangeLoop state. Messages are tagged with phase metadata for filtered
    retrieval (e.g., execute_step-only projection for CoreAgent).
    """

    max_inline_chars: int = 4000
    max_entry_chars_before_spill: int = 1500
    max_entries: int = 200
    compact_fn: Callable[[list[_LedgerEntry]], str | None] | None = None
    _entries: list[_LedgerEntry] = field(default_factory=list)
    _step_lines: list[str] = field(default_factory=list)

    def record_message(self, message: BaseMessage, phase: str) -> None:
        """Append a message to the ledger with phase metadata."""
        self._entries.append(_LedgerEntry(message=message, phase=phase))
        if self.max_entries > 0 and len(self._entries) > self.max_entries:
            self.compact()

    def get_messages(self, phases: list[str] | None = None) -> list[BaseMessage]:
        """Return messages, optionally filtered by phase."""
        if phases is None:
            return [e.message for e in self._entries]
        phase_set = set(phases)
        return [e.message for e in self._entries if e.phase in phase_set]

    def project_for_plan(
        self,
        *,
        max_messages: int = 0,
        max_total_chars: int = 0,
        max_per_message_chars: int = 0,
    ) -> list[BaseMessage]:
        """Return ledger messages for plan prompts (all phases).

        Applies optional bounding via message count, total chars, and
        per-message char limits. Mirrors
        ``project_loop_messages_for_plan`` from
        ``loop/prompts/plan_ledger_projection.py``.
        """
        messages = [e.message for e in self._entries]
        if max_messages <= 0 and max_total_chars <= 0 and max_per_message_chars <= 0:
            return list(messages)

        out = list(messages)
        if max_messages > 0 and len(out) > max_messages:
            out = out[-max_messages:]

        if max_per_message_chars > 0:
            out = [self._cap_message(m, max_per_message_chars) for m in out]

        if max_total_chars > 0:
            out = self._trim_total_chars(out, max_total_chars)

        return out

    def project_for_core_agent(self) -> list[BaseMessage]:
        """Return only execute_step phase messages for CoreAgent.

        Also includes non-loop plain HumanMessage/AIMessage objects
        (phase=None) for compatibility with early ledger entries.
        """
        out: list[BaseMessage] = []
        for entry in self._entries:
            if entry.phase == "execute_step":
                out.append(entry.message)
            elif entry.phase is None and isinstance(entry.message, (HumanMessage, AIMessage)):
                out.append(entry.message)
        return out

    def compact(self) -> None:
        """Compact old entries when count exceeds max_entries.

        If a compact_fn is provided, it receives the oldest entries and returns
        a summary string (or None to skip compaction). The summary replaces
        those entries as a single SystemMessage.

        If no compact_fn is set, entries beyond max_entries are dropped.
        """
        if self.max_entries <= 0:
            return
        if len(self._entries) <= self.max_entries:
            return

        excess = len(self._entries) - self.max_entries
        old_entries = self._entries[:excess]

        if self.compact_fn is not None:
            try:
                summary = self.compact_fn(old_entries)
            except Exception:
                logger.warning("Compaction function failed, dropping oldest entries", exc_info=True)
                self._entries = self._entries[excess:]
                return
            if summary:
                self._entries = [
                    _LedgerEntry(message=SystemMessage(content=summary), phase="compacted"),
                    *self._entries[excess:],
                ]
                return

        self._entries = self._entries[excess:]

    def entries(self, phases: list[str] | None = None) -> list[tuple[BaseMessage, str | None]]:
        """Return (message, phase) tuples, optionally filtered by phase."""
        if phases is None:
            return [(e.message, e.phase) for e in self._entries]
        phase_set = set(phases)
        return [(e.message, e.phase) for e in self._entries if e.phase in phase_set]

    def record_step_result(
        self,
        step_id: str,
        description: str,
        output: str | None,
        error: str | None,
        success: bool,
    ) -> None:
        """Record step outcome summary (mirrors LoopWorkingMemory)."""
        desc = (description or "").strip().replace("\n", " ")
        if len(desc) > _DESC_INLINE_MAX:
            desc = desc[: _DESC_INLINE_MAX - 3] + "…"

        body = (output or "").strip() if success else (error or "").strip()
        if success:
            if body:
                cap = min(_INLINE_SUCCESS_BODY_CAP, self.max_entry_chars_before_spill)
                line = f"[{step_id}] ✓ {desc} — {body[:cap]}{'…' if len(body) > cap else ''}"
            else:
                line = f"[{step_id}] ✓ {desc} — (no text output)"
        else:
            err = body[:_ERR_INLINE_MAX] + ("…" if len(body) > _ERR_INLINE_MAX else "")
            line = f"[{step_id}] ✗ {desc} — {err}"

        self._step_lines.append(line)

    def render_for_reason(self, *, max_chars: int | None = None) -> str:
        """Build condensed text summary for reasoning prompts."""
        cap = max_chars if max_chars is not None else self.max_inline_chars
        if not self._step_lines:
            return ""
        text = "\n".join(self._step_lines)
        if len(text) <= cap:
            return text
        return text[: cap - 20] + "\n… (truncated)"

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()
        self._step_lines.clear()

    @staticmethod
    def _cap_message(msg: BaseMessage, max_chars: int) -> BaseMessage:
        text = getattr(msg, "content", "")
        if isinstance(text, str) and len(text) <= max_chars:
            return msg
        if isinstance(text, str):
            clipped = text[: max(0, max_chars - 20)] + "\n…[truncated]\n"
            if isinstance(msg, HumanMessage):
                return HumanMessage(content=clipped)
            if isinstance(msg, AIMessage):
                return AIMessage(content=clipped)
        return msg

    @staticmethod
    def _trim_total_chars(messages: list[BaseMessage], max_chars: int) -> list[BaseMessage]:
        def _text_len(m: BaseMessage) -> int:
            content = getattr(m, "content", "")
            return len(content) if isinstance(content, str) else 0

        out = list(messages)
        while out and sum(_text_len(m) for m in out) > max_chars:
            if len(out) == 1:
                break
            out.pop(0)
        return out
