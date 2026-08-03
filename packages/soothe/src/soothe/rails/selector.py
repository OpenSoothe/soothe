"""Resolve which LoopRail (if any) applies to a job submit (IG-678 P2)."""

from __future__ import annotations

from pathlib import Path


def resolve_rail_id(
    explicit: str | None,
    *,
    workspace: str | None = None,
    default_rail: str | None = None,
) -> str | None:
    """Pick a rail id: explicit → workspace ``.rail-default`` → config → None.

    There is no invented ``default.yml`` rail; missing resolution means no-rail.
    """
    if explicit and explicit.strip():
        return explicit.strip()

    if workspace and str(workspace).strip():
        marker = Path(workspace).expanduser() / ".soothe" / "rails" / ".rail-default"
        if marker.is_file():
            for line in marker.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line

    if default_rail and str(default_rail).strip():
        return str(default_rail).strip()
    return None
