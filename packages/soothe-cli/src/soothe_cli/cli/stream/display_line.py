"""DisplayLine dataclass for structured CLI output."""

from __future__ import annotations

from dataclasses import dataclass

_MS_PER_SECOND = 1000


@dataclass
class DisplayLine:
    """Structured output unit for CLI stream display.

    Attributes:
        level: Semantic level (1=goal, 2=step/tool, 3=result); indent is flat for all.
        content: Text content to display.
        icon: Icon prefix ("●", "○", "⚙", "✓", "✗", "→", etc.).
        indent: Indentation string (headless stream uses no tree indent).
        status: Optional status suffix ("running" for parallel tools).
        duration_ms: Optional duration in milliseconds.
        source_prefix: Optional source identifier for debug mode (e.g., "[main]", "[subagent:research]").
    """

    level: int
    content: str
    icon: str
    indent: str
    status: str | None = None
    duration_ms: int | None = None
    source_prefix: str | None = None

    def format(self) -> str:
        """Format the display line as a string.

        Returns:
            Formatted line ready for output.
        """
        parts = []

        # Add source prefix first if present (debug mode)
        if self.source_prefix:
            parts.append(self.source_prefix)
            parts.append(" ")

        # Handle empty icon (connector already in indent)
        if self.icon:
            parts.extend([self.indent, self.icon, " ", self.content])
        else:
            parts.extend([self.indent, self.content])

        if self.status:
            parts.append(f" [{self.status}]")

        if self.duration_ms is not None:
            if self.duration_ms >= _MS_PER_SECOND:
                parts.append(f" ({self.duration_ms / _MS_PER_SECOND:.1f}s)")
            else:
                parts.append(f" ({self.duration_ms}ms)")

        return "".join(parts)


def indent_for_level(level: int) -> str:
    """Get indentation string for a display level.

    IG-182: Headless CLI uses flat layout for levels 1-2, but tree indentation
    for level-3 child nodes (step results with "|__" connector).

    Args:
        level: Display level (1=goal, 2=step/tool, 3=result child).

    Returns:
        Indentation string: "" for level 1-2, "  " for level 3 (tree child).
    """
    if level >= 3:  # noqa: PLR2004
        return "  "  # 2-space indent for tree children (IG-182)
    return ""  # Flat layout for goal/step headers


__all__ = ["DisplayLine", "indent_for_level"]
