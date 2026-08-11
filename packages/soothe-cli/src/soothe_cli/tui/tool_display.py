"""Step-card tool activity line formatting (IG-402, IG-428)."""

from __future__ import annotations

import json
from typing import Any

from soothe_sdk.display.message_processing import (
    _normalize_tool_name_for_arg_map,
    extract_tool_args_dict,
)
from soothe_sdk.tools.metadata import get_tool_meta
from soothe_sdk.utils import get_tool_display_name
from soothe_sdk.utils.formatting import convert_and_abbreviate_path
from soothe_sdk.wire.protocol import preview_first

from soothe_cli.runtime.presentation.duration_format import format_duration_ms

_ARG_PREVIEW_MAX_CHARS = 80
_EDIT_STRING_PREVIEW_MAX_CHARS = 30
_ERROR_STATUS_TAIL_MAX_CHARS = 48
_EDIT_STRING_ARG_KEYS = frozenset({"old_string", "new_string"})
_SKIP_ARG_KEYS = frozenset({"_raw", "_subgraph_tool", "value"})
_GENERIC_ERROR_TAILS = frozenset({"", "error", "failed", "tool error"})


def display_width(text: str) -> int:
    """Terminal display width of *text* (wide chars count as 2 columns).

    Thin wrapper over the canonical ``termaid.utils.display_width`` so callers
    in this module don't each need a lazy import. Falls back to ``len()`` if
    termaid is unavailable (e.g. minimal test environments).
    """
    try:
        from termaid.utils import display_width as _dw

        return _dw(text)
    except ImportError:
        return len(text)


def _char_width(ch: str) -> int:
    """Display width of a single character (2 for East-Asian wide / emoji)."""
    try:
        from termaid.utils import _is_wide

        return 2 if _is_wide(ch) else 1
    except ImportError:
        return 1


def truncate_to_width(text: str, max_cols: int, *, ellipsis: str = "…") -> str:
    """Truncate *text* to ``max_cols`` terminal columns, appending an ellipsis.

    The ellipsis itself counts toward the budget, so the returned string never
    exceeds ``max_cols``. Slices by character count using display-width
    accounting so East-Asian wide / emoji characters (2 columns each) are not
    split mid-cell. When ``max_cols`` is non-positive, returns *text* unchanged.
    """
    if max_cols <= 0 or display_width(text) <= max_cols:
        return text
    ellipsis_width = display_width(ellipsis)
    target = max_cols - ellipsis_width
    if target <= 0:
        # Budget too small for content + ellipsis; return just the ellipsis.
        return ellipsis[:max_cols] if ellipsis_width > max_cols else ellipsis
    out: list[str] = []
    width = 0
    for ch in text:
        w = _char_width(ch)
        if width + w > target:
            break
        out.append(ch)
        width += w
    return "".join(out) + ellipsis


def compact_arg_text(text: str) -> str:
    """Collapse whitespace/newlines so activity lines stay on one row."""
    return " ".join(text.split())


def _coerce_arg_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return compact_arg_text(value.strip())
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, dict)):
        try:
            return preview_first(json.dumps(value, default=str), _ARG_PREVIEW_MAX_CHARS)
        except (TypeError, ValueError):
            return preview_first(str(value), _ARG_PREVIEW_MAX_CHARS)
    return preview_first(str(value), _ARG_PREVIEW_MAX_CHARS)


def _arg_preview_max_chars(key: str) -> int:
    if key in _EDIT_STRING_ARG_KEYS:
        return _EDIT_STRING_PREVIEW_MAX_CHARS
    return _ARG_PREVIEW_MAX_CHARS


def _format_arg_value(tool_name: str, key: str, value: Any, *, max_chars: int | None = None) -> str:
    text = _coerce_arg_text(value)
    if not text:
        return ""
    meta = get_tool_meta(_normalize_tool_name_for_arg_map(tool_name))
    if meta and key in meta.path_arg_keys:
        return convert_and_abbreviate_path(text)
    cap = max_chars if max_chars is not None else _arg_preview_max_chars(key)
    return preview_first(text, cap)


def _ordered_arg_keys(tool_name: str, clean: dict[str, Any]) -> list[str]:
    """Meta priority first, then any remaining keys (stable sorted)."""
    meta = get_tool_meta(_normalize_tool_name_for_arg_map(tool_name))
    ordered: list[str] = []
    if meta and meta.arg_keys:
        ordered.extend(k for k in meta.arg_keys if k in clean)
    for key in sorted(clean.keys()):
        if key not in ordered:
            ordered.append(key)
    return ordered


def _args_preview(tool_name: str, args: dict[str, Any], *, max_chars: int | None = None) -> str:
    """Comma-separated arg summary: primary value bare, extras as ``key=value``.

    ``max_chars`` bounds each value's width (falls back to the per-key default
    when ``None``). The caller may further truncate the whole command line to a
    terminal-column budget via :func:`format_step_tool_activity_line`.
    """
    normalized = extract_tool_args_dict(args or {})
    if not normalized and isinstance(args, dict):
        raw_value = args.get("value")
        if isinstance(raw_value, str) and raw_value.strip():
            try:
                loaded = json.loads(raw_value)
            except (TypeError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                normalized = loaded
    source_args = normalized if normalized else (args or {})
    clean = {k: v for k, v in source_args.items() if k not in _SKIP_ARG_KEYS}
    if not clean:
        return ""
    segments: list[str] = []
    primary_emitted = False
    for key in _ordered_arg_keys(tool_name, clean):
        text = _format_arg_value(tool_name, key, clean[key], max_chars=max_chars)
        if not text:
            continue
        if not primary_emitted:
            segments.append(text)
            primary_emitted = True
        else:
            segments.append(f"{key}={text}")
    return ", ".join(segments)


def format_step_tool_activity_command(
    tool_name: str, args: dict[str, Any], *, max_cols: int | None = None
) -> str:
    """One-line invocation summary: ``DisplayName(arg)`` or ``DisplayName``.

    ``max_cols`` is an optional terminal-column budget for the *whole* command
    (display name + parens + args). When set, args are first capped per-value
    to the remaining width, then the assembled command is width-truncated with
    an ellipsis so it never exceeds ``max_cols``. When ``None`` (tests / unmounted),
    the fixed per-key caps apply and no whole-line truncation occurs.
    """
    canonical = _normalize_tool_name_for_arg_map((tool_name or "").strip() or "tool")
    display = get_tool_display_name(canonical)
    if max_cols is not None and max_cols > 0:
        # Reserve "DisplayName(" + ")" overhead for the arg budget.
        overhead = display_width(display) + 2  # "(" and ")"
        arg_budget = max(0, max_cols - overhead)
        preview = _args_preview(canonical, args or {}, max_chars=arg_budget)
    else:
        preview = _args_preview(canonical, args or {})
    if preview:
        command = f"{display}({preview})"
    else:
        command = display
    if max_cols is not None and max_cols > 0:
        command = truncate_to_width(command, max_cols)
    elif max_cols is not None and max_cols <= 0:
        # No room for even the command; drop it so only the tail shows.
        return ""
    return command


def abbreviate_tool_error_message(
    error: str, *, max_chars: int = _ERROR_STATUS_TAIL_MAX_CHARS
) -> str:
    """One-line error summary for a failed tool row (no gutter or phase icon)."""
    text = str(error or "").strip()
    if not text:
        return ""

    parsed: dict[str, Any] | None = None
    if text.startswith("{") and text.endswith("}"):
        try:
            loaded = json.loads(text)
        except (TypeError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            parsed = loaded
            for key in ("error", "message", "detail", "reason"):
                val = loaded.get(key)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    break

    first_line = compact_arg_text(text.splitlines()[0].strip())
    lowered = first_line.lower()
    for prefix in (
        "error executing tool:",
        "tool execution error:",
        "tool error:",
        "error:",
    ):
        if lowered.startswith(prefix):
            first_line = first_line[len(prefix) :].strip()
            break

    summary = preview_first(first_line, max_chars)
    if summary.lower() in _GENERIC_ERROR_TAILS:
        return ""
    if parsed is not None and parsed.get("success") is False and not summary:
        return ""
    return summary


def format_step_tool_activity_status_tail(
    phase: str,
    *,
    duration_ms: int = 0,
    error: str = "",
) -> str:
    """Trailing status fragment (duration, failure); phase icon is rendered separately."""
    p = (phase or "pending").strip().lower()
    if p == "success" and duration_ms > 0:
        return f" ({format_duration_ms(duration_ms)})"
    if p == "error":
        summary = abbreviate_tool_error_message(error)
        if summary:
            return f" · {summary}"
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
    error: str = "",
    max_cols: int | None = None,
) -> str:
    """Full activity text without gutter or phase icon.

    ``max_cols`` is an optional terminal-column budget for the *whole* line
    (command + status tail). When set, the tail is reserved first (it carries
    duration/error info the user needs), then the command is truncated to fit
    so the assembled line never exceeds ``max_cols`` — one row, no wrap. If
    the tail alone exceeds the budget (e.g. a long error summary on a narrow
    terminal), the tail is truncated too. When ``None``, no whole-line
    truncation occurs (preserves prior behavior for tests and unmounted widgets).
    """
    tail = format_step_tool_activity_status_tail(
        phase,
        duration_ms=duration_ms,
        error=error,
    )
    command_max = None
    if max_cols is not None and max_cols > 0:
        # If the tail alone exceeds the budget, truncate it first.
        tail_width = display_width(tail)
        if tail_width >= max_cols:
            tail = truncate_to_width(tail.strip(), max_cols)
            command_max = 0
        else:
            command_max = max(0, max_cols - tail_width)
    command = format_step_tool_activity_command(tool_name, args, max_cols=command_max)
    return f"{command}{tail}"
