"""Render fenced Mermaid diagrams for TUI markdown (IG-657).

Goal-completion synthesis emits mermaid code fences; Rich's default
``CodeBlock`` shows them as source. This helper expands supported diagrams to
Unicode/ASCII art via ``termaid``, with progressive compaction to fit the
card width.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MERMAID_LEXERS = frozenset({"mermaid", "mmd"})

# Progressive compaction steps (mirrors termaid CLI ``_auto_fit``).
_COMPACT_STEPS: tuple[dict[str, int], ...] = (
    {},
    {"gap": 2},
    {"gap": 1},
    {"gap": 1, "padding_x": 2},
    {"gap": 1, "padding_x": 0},
    {"gap": 1, "padding_x": 0, "padding_y": 0},
)


def is_mermaid_lexer(lexer_name: str | None) -> bool:
    """Return True when a fenced code info string is a Mermaid language tag."""
    if not lexer_name:
        return False
    return lexer_name.partition(" ")[0].strip().lower() in _MERMAID_LEXERS


def _max_line_width(text: str) -> int:
    from termaid.utils import display_width

    return max((display_width(line) for line in text.split("\n")), default=0)


def _render_plain(source: str, **kwargs: int) -> str:
    from termaid import render

    return (render(source, **kwargs) or "").rstrip("\n")


def render_mermaid_art(
    source: str,
    *,
    max_width: int | None = None,
) -> str | None:
    """Render Mermaid source to terminal art, or ``None`` on failure.

    Args:
        source: Mermaid diagram body (without fence markers).
        max_width: Optional column budget; re-renders with smaller gap/padding
            when the diagram exceeds this width.

    Returns:
        Non-empty diagram string, or ``None`` when rendering fails / is empty.
    """
    text = (source or "").strip()
    if not text:
        return None

    try:
        art = _render_plain(text)
    except Exception:  # noqa: BLE001 — fall back to code fence
        logger.debug("mermaid render failed", exc_info=True)
        return None

    if not art.strip():
        return None

    if max_width is None or max_width <= 0 or _max_line_width(art) <= max_width:
        return art

    best = art
    for overrides in _COMPACT_STEPS[1:]:
        try:
            candidate = _render_plain(text, **overrides)
        except Exception:  # noqa: BLE001
            continue
        if not candidate.strip():
            continue
        best = candidate
        if _max_line_width(candidate) <= max_width:
            return candidate

    return best


__all__ = [
    "is_mermaid_lexer",
    "render_mermaid_art",
]
