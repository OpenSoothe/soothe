"""In-memory loop working memory with spill under SOOTHE_HOME (RFC-203)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)

_DESC_INLINE_MAX = 160
_ERR_INLINE_MAX = 500
_INLINE_SUCCESS_BODY_CAP = 800


def _thread_slug(thread_id: str) -> str:
    """Map thread id to a single filesystem path component."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", thread_id.strip())[:128]
    return cleaned or "default"


def _spill_subdir_under_home(spill_subdir: str) -> Path:
    """Normalize config path to a directory relative to ``SOOTHE_HOME``."""
    s = (spill_subdir or "loop").strip().strip("/")
    if s.startswith(".soothe/"):
        s = s[len(".soothe/") :]
    elif s == ".soothe":
        s = "loop"
    return Path(s) if s else Path("loop")


@dataclass
class LoopWorkingMemory:
    """Accumulate agentic-loop facts for Reason prompts; spill large outputs under SOOTHE_HOME.

    Args:
        max_inline_chars: Cap for ``render_for_reason`` aggregate text.
        max_entry_chars_before_spill: Spill raw step output when longer than this.
        spill_subdir: Directory under ``SOOTHE_HOME`` for spill files.
    """

    max_inline_chars: int = 4000
    max_entry_chars_before_spill: int = 1500
    spill_subdir: str = "loop"
    _lines: list[str] = field(default_factory=list)
    _spill_seq: dict[tuple[str, str], int] = field(default_factory=dict)

    def clear(self) -> None:
        """Remove all entries (e.g. new goal)."""
        self._lines.clear()
        self._spill_seq.clear()

    def _next_spill_seq(self, thread_slug: str, step_id: str) -> int:
        key = (thread_slug, step_id)
        n = self._spill_seq.get(key, 0) + 1
        self._spill_seq[key] = n
        return n

    def _write_spill(self, thread_slug: str, step_id: str, body: str) -> str:
        """Write spill file under SOOTHE_HOME; return path relative to SOOTHE_HOME (posix)."""
        seq = self._next_spill_seq(thread_slug, step_id)
        safe_step = re.sub(r"[^a-zA-Z0-9._-]+", "_", step_id)[:64] or "step"
        home = Path(SOOTHE_HOME).expanduser()
        rel_dir = _spill_subdir_under_home(self.spill_subdir) / thread_slug
        name = f"step-{safe_step}-{seq}.md"
        abs_dir = (home / rel_dir).resolve()
        abs_dir.mkdir(parents=True, exist_ok=True)
        path = abs_dir / name
        header = f"# Loop working memory spill: step `{step_id}`\n\n"
        path.write_text(header + body, encoding="utf-8")
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
        _ = workspace  # Spill files live under SOOTHE_HOME (IG-124); arg kept for API stability.
        desc = (description or "").strip().replace("\n", " ")
        if len(desc) > _DESC_INLINE_MAX:
            desc = desc[: _DESC_INLINE_MAX - 3] + "…"

        body = (output or "").strip() if success else (error or "").strip()
        slug = _thread_slug(thread_id)
        line: str
        if success:
            if body and len(body) > self.max_entry_chars_before_spill:
                try:
                    rel = self._write_spill(slug, step_id, body)
                    line = f"[{step_id}] ✓ {desc} — full output in `{rel}` (under SOOTHE_HOME; use read_file)"
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
