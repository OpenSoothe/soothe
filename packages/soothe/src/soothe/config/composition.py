"""Composition helpers for split host configuration files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soothe.config.ownership import (
    validate_host_file_ownership,
    validate_nano_file_ownership,
)


@dataclass(frozen=True, slots=True)
class CompositionConflict:
    """Conflicting assignment for one merged key path."""

    key_path: str
    base_value: Any
    overlay_value: Any


class CompositionConflictError(ValueError):
    """Raised when split config composition finds incompatible overlaps."""

    def __init__(self, conflicts: list[CompositionConflict]) -> None:
        self.conflicts = list(conflicts)
        details = "; ".join(
            f"{c.key_path}: base={c.base_value!r}, overlay={c.overlay_value!r}"
            for c in self.conflicts
        )
        super().__init__(f"Config composition conflict: {details}")


def _merge_dicts(
    base: dict[str, Any],
    overlay: dict[str, Any],
    *,
    path: str = "",
) -> tuple[dict[str, Any], list[CompositionConflict]]:
    merged = dict(base)
    conflicts: list[CompositionConflict] = []

    for key, overlay_value in overlay.items():
        child_path = f"{path}.{key}" if path else key
        if key not in merged:
            merged[key] = overlay_value
            continue

        base_value = merged[key]
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            nested_merged, nested_conflicts = _merge_dicts(
                base_value,
                overlay_value,
                path=child_path,
            )
            merged[key] = nested_merged
            conflicts.extend(nested_conflicts)
            continue

        if base_value == overlay_value:
            merged[key] = overlay_value
            continue

        conflicts.append(
            CompositionConflict(
                key_path=child_path,
                base_value=base_value,
                overlay_value=overlay_value,
            )
        )

    return merged, conflicts


def compose_host_agent_config(
    nano_data: dict[str, Any],
    soothe_data: dict[str, Any],
    *,
    nano_source_file: str = "nano.yml",
    soothe_source_file: str = "soothe.yml",
) -> dict[str, Any]:
    """Compose effective host config from ``nano.yml`` base and ``soothe.yml`` overlay."""
    validate_nano_file_ownership(nano_data, source_file=nano_source_file)
    validate_host_file_ownership(soothe_data, source_file=soothe_source_file)

    merged, conflicts = _merge_dicts(nano_data, soothe_data)
    if conflicts:
        raise CompositionConflictError(conflicts)
    return merged


__all__ = ["CompositionConflict", "CompositionConflictError", "compose_host_agent_config"]
