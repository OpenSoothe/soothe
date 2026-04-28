"""In-memory loop working memory with spill under SOOTHE_HOME/data/threads/{thread_id}/working_memory/ (RFC-203)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from soothe.cognition.agent_loop.state.persistence.directory_manager import (
    PersistenceDirectoryManager,
)

logger = logging.getLogger(__name__)

_DESC_INLINE_MAX = 160
_ERR_INLINE_MAX = 500
_INLINE_SUCCESS_BODY_CAP = 800


@dataclass
class LoopWorkingMemory:
    """Accumulate agentic-loop facts for Reason prompts.

    Spills large outputs under ``SOOTHE_HOME/data/threads/{thread_id}/working_memory/``.

    Args:
        thread_id: Canonical thread identifier; spill path is ``data/threads/{thread_id}/working_memory/``.
        max_inline_chars: Cap for ``render_for_reason`` aggregate text.
        max_entry_chars_before_spill: Spill raw step output when longer than this.
    """

    thread_id: str
    max_inline_chars: int = 4000
    max_entry_chars_before_spill: int = 1500
    _lines: list[str] = field(default_factory=list)
    _spill_seq: dict[str, int] = field(default_factory=dict)

    def clear(self) -> None:
        """Remove all entries (e.g. new goal)."""
        self._lines.clear()
        self._spill_seq.clear()

    def _next_spill_seq(self, step_id: str) -> int:
        n = self._spill_seq.get(step_id, 0) + 1
        self._spill_seq[step_id] = n
        return n

    def _write_spill(self, step_id: str, body: str) -> str:
        """Write spill file under ``SOOTHE_HOME/data/threads/{thread_id}/working_memory/``; return relative path (posix)."""
        seq = self._next_spill_seq(step_id)
        safe_step = re.sub(r"[^a-zA-Z0-9._-]+", "_", step_id)[:64] or "step"
        # Use new isolated directory structure (RFC-409)
        abs_dir = (
            PersistenceDirectoryManager.get_thread_directory(self.thread_id) / "working_memory"
        )
        abs_dir.mkdir(parents=True, exist_ok=True)
        name = f"step-{safe_step}-{seq}.md"
        path = abs_dir / name
        header = f"# Loop working memory spill: step `{step_id}`\n\n"
        path.write_text(header + body, encoding="utf-8")
        # Return relative path from SOOTHE_HOME for consistency
        rel_dir = (
            PersistenceDirectoryManager.get_thread_directory(self.thread_id).relative_to(
                PersistenceDirectoryManager.get_loops_directory().parent
            )
            / "working_memory"
        )
        rel = (rel_dir / name).as_posix()
        logger.info("LoopWorkingMemory spilled %d chars to %s", len(body), path)
        return rel

    def record_step_result(
        self,
        *,
        step_id: str,
        description: str,
        output: str | None,
        error: str | None,
        success: bool,
        workspace: str | None,
        thread_id: str,
    ) -> None:
        """Record one Act step outcome."""
        _ = workspace  # Spill files live under SOOTHE_HOME/data/threads/{thread_id}/; arg kept for API stability.
        _ = thread_id  # thread_id is set in constructor; kept for protocol compatibility.
        desc = (description or "").strip().replace("\n", " ")
        if len(desc) > _DESC_INLINE_MAX:
            desc = desc[: _DESC_INLINE_MAX - 3] + "…"

        body = (output or "").strip() if success else (error or "").strip()
        line: str
        if success:
            if body and len(body) > self.max_entry_chars_before_spill:
                try:
                    rel = self._write_spill(step_id, body)
                    line = f"[{step_id}] ✓ {desc} — full output in `{rel}` (use read_file)"
                except OSError:
                    logger.exception("Working memory spill failed; truncating inline")
                    line = f"[{step_id}] ✓ {desc} — {body[: self.max_entry_chars_before_spill]}…"
            elif body:
                cap = min(_INLINE_SUCCESS_BODY_CAP, self.max_entry_chars_before_spill)
                line = f"[{step_id}] ✓ {desc} — {body[:cap]}{'…' if len(body) > cap else ''}"
            else:
                line = f"[{step_id}] ✓ {desc} — (no text output)"
        else:
            err = body[:_ERR_INLINE_MAX] + ("…" if len(body) > _ERR_INLINE_MAX else "")
            line = f"[{step_id}] ✗ {desc} — {err}"

        self._lines.append(line)

    def render_for_reason(self, *, max_chars: int | None = None) -> str:
        """Build prompt section text; respect ``max_inline_chars`` or override."""
        cap = max_chars if max_chars is not None else self.max_inline_chars
        if not self._lines:
            return ""
        text = "\n".join(self._lines)
        if len(text) <= cap:
            return text
        return text[: cap - 20] + "\n… (truncated)"
