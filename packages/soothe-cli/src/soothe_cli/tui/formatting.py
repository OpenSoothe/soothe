"""Lightweight text-formatting helpers.

Keep this module free of heavy dependencies so it can be imported anywhere
in the CLI without pulling in large frameworks.

Implementation lives in :mod:`soothe_cli.shared.duration_format` so shared code
does not need to import the ``soothe_cli.tui`` package (avoids import cycles).
"""

from __future__ import annotations

from soothe_cli.shared.duration_format import format_duration, format_duration_ms

__all__ = ["format_duration", "format_duration_ms"]
