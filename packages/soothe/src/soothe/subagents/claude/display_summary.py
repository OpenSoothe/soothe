"""One-line summary for Claude subagent completion display (IG-344)."""

from __future__ import annotations


def claude_text_summary_for_display(text: str, *, max_len: int = 160) -> str:
    """Derive a short summary from Claude Code assistant text (no extra LLM call).

    Prefers the first markdown heading line; otherwise the first non-empty line,
    then a simple first-sentence heuristic. Whitespace is collapsed to a single line.

    Args:
        text: Full concatenated assistant text from the Claude Code session.
        max_len: Maximum length of the returned summary.

    Returns:
        Non-empty summary string, or empty string when there is nothing to show.
    """
    raw = (text or "").strip()
    if not raw:
        return ""

    chosen = ""
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            chosen = stripped.lstrip("#").strip()
            if chosen:
                break

    if not chosen:
        for line in raw.split("\n"):
            stripped = line.strip()
            if stripped:
                chosen = stripped
                break

    if not chosen:
        chosen = " ".join(raw.split())

    # First sentence / clause (light heuristic)
    for sep in (". ", "! ", "? ", "\n"):
        pos = chosen.find(sep)
        if pos >= 20:
            chosen = chosen[: pos + 1].strip()
            break

    out = " ".join(chosen.split())
    if len(out) > max_len:
        return out[: max_len - 1] + "…"
    return out


__all__ = ["claude_text_summary_for_display"]
