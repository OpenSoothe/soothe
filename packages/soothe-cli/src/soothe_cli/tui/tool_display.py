"""Step-card tool activity line formatting (IG-402, IG-428)."""

from __future__ import annotations

import json
from typing import Any

from soothe_sdk.client.protocol import preview_first
from soothe_sdk.tools.metadata import get_tool_meta
from soothe_sdk.utils import get_tool_display_name
from soothe_sdk.utils.formatting import convert_and_abbreviate_path

from soothe_cli.runtime.parse.message_processing import _normalize_tool_name_for_arg_map
from soothe_cli.runtime.presentation.duration_format import format_duration_ms

_ARG_PREVIEW_MAX_CHARS = 80
_SKIP_ARG_KEYS = frozenset({"_raw"})


def _coerce_arg_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, dict)):
        try:
            return preview_first(json.dumps(value, default=str), _ARG_PREVIEW_MAX_CHARS)
        except (TypeError, ValueError):
            return preview_first(str(value), _ARG_PREVIEW_MAX_CHARS)
    return preview_first(str(value), _ARG_PREVIEW_MAX_CHARS)


def _format_arg_value(tool_name: str, key: str, value: Any) -> str:
    text = _coerce_arg_text(value)
    if not text:
        return ""
    meta = get_tool_meta(_normalize_tool_name_for_arg_map(tool_name))
    if meta and key in meta.path_arg_keys:
        return convert_and_abbreviate_path(text)
    return preview_first(text, _ARG_PREVIEW_MAX_CHARS)


def _primary_arg_preview(tool_name: str, args: dict[str, Any]) -> str:
    clean = {k: v for k, v in (args or {}).items() if k not in _SKIP_ARG_KEYS}
    if not clean:
        return ""
    meta = get_tool_meta(_normalize_tool_name_for_arg_map(tool_name))
    keys: tuple[str, ...] = ()
    if meta and meta.arg_keys:
        keys = meta.arg_keys
    else:
        keys = tuple(sorted(clean.keys()))
    for key in keys:
        if key not in clean:
            continue
        text = _format_arg_value(tool_name, key, clean[key])
        if text:
            return text
    for key, value in clean.items():
        text = _format_arg_value(tool_name, key, value)
        if text:
            return text
    return ""


def format_step_tool_activity_command(tool_name: str, args: dict[str, Any]) -> str:
    """One-line invocation summary: ``DisplayName(arg)`` or ``DisplayName``."""
    canonical = _normalize_tool_name_for_arg_map((tool_name or "").strip() or "tool")
    display = get_tool_display_name(canonical)
    preview = _primary_arg_preview(canonical, args or {})
    if preview:
        return f"{display}({preview})"
    return display


def format_step_tool_activity_status_tail(
    phase: str,
    *,
    duration_ms: int = 0,
) -> str:
    """Trailing status fragment (duration, failure); phase icon is rendered separately."""
    p = (phase or "pending").strip().lower()
    if p == "success" and duration_ms > 0:
        return f" ({format_duration_ms(duration_ms)})"
    if p == "error":
        return " · failed"
    if p == "rejected":
        return " · rejected"
    if p == "skipped":
        return " · skipped"
    if p == "running":
        return " · running"
    return ""


def format_step_tool_activity_line(
    tool_name: str,
    args: dict[str, Any],
    phase: str,
    *,
    duration_ms: int = 0,
) -> str:
    """Full activity text without gutter or phase icon."""
    command = format_step_tool_activity_command(tool_name, args)
    tail = format_step_tool_activity_status_tail(phase, duration_ms=duration_ms)
    return f"{command}{tail}"
