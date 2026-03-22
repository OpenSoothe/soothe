"""Progress event rendering for CLI output.

This module provides backward-compatible rendering via registry-based dispatch
(RFC-0015). The implementation delegates to CliEventRenderer for O(1) lookup
instead of the old O(n) if-elif chains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.ux.shared.progress_verbosity import ProgressVerbosity


def render_progress_event(
    data: dict,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    """Render a soothe.* event as a structured progress line to stderr.

    This function delegates to CliEventRenderer which uses registry-based
    O(1) dispatch instead of O(n) if-elif chains (RFC-0015).

    Args:
        data: Event dict with 'type' key.
        prefix: Optional prefix (unused in new implementation, kept for compat).
        verbosity: Verbosity level for filtering.
    """
    from soothe.ux.cli.rendering.cli_event_renderer import render_progress_event as _render

    _render(data, prefix=prefix, verbosity=verbosity)
