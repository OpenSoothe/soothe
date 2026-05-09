"""Public API for the textual_adapter sub-package.

Heavy submodules (notably ``_turn``) load on demand via PEP 562 ``__getattr__``
so importing ``TextualUIAdapter`` for startup does not pull the full first-turn
dependency graph onto the event loop.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "TextualUIAdapter",
    "execute_task_textual",
    "print_usage_table",
    "ModelStats",
    "SessionStats",
    "SpinnerStatus",
    "format_token_count",
    "AGENT_LOOP_GOAL_COMPLETED",
    "AGENT_LOOP_GOAL_STARTED",
    "AGENT_LOOP_STEP_COMPLETED",
    "AGENT_LOOP_STEP_STARTED",
]

# (module path, attribute name) — resolved lazily and cached on the module dict.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # --- _adapter -----------------------------------------------------------------
    "AGENT_LOOP_GOAL_COMPLETED": (
        "soothe_cli.tui.textual_adapter._adapter",
        "AGENT_LOOP_GOAL_COMPLETED",
    ),
    "AGENT_LOOP_GOAL_STARTED": (
        "soothe_cli.tui.textual_adapter._adapter",
        "AGENT_LOOP_GOAL_STARTED",
    ),
    "AGENT_LOOP_STEP_COMPLETED": (
        "soothe_cli.tui.textual_adapter._adapter",
        "AGENT_LOOP_STEP_COMPLETED",
    ),
    "AGENT_LOOP_STEP_STARTED": (
        "soothe_cli.tui.textual_adapter._adapter",
        "AGENT_LOOP_STEP_STARTED",
    ),
    "ModelStats": ("soothe_cli.tui.textual_adapter._adapter", "ModelStats"),
    "SessionStats": ("soothe_cli.tui.textual_adapter._adapter", "SessionStats"),
    "SpinnerStatus": ("soothe_cli.tui.textual_adapter._adapter", "SpinnerStatus"),
    "TextualUIAdapter": ("soothe_cli.tui.textual_adapter._adapter", "TextualUIAdapter"),
    "format_token_count": ("soothe_cli.tui.textual_adapter._adapter", "format_token_count"),
    # --- other submodules ---------------------------------------------------------
    "execute_task_textual": ("soothe_cli.tui.textual_adapter._turn", "execute_task_textual"),
    "print_usage_table": ("soothe_cli.tui.textual_adapter._stream_formatting", "print_usage_table"),
    # --- test / internal re-exports (historically imported from package root) ---
    "_defer_first_tool_card_mount_until_final_stream_chunk": (
        "soothe_cli.tui.textual_adapter._stream_messages",
        "_defer_first_tool_card_mount_until_final_stream_chunk",
    ),
    "_defer_tool_card_for_empty_streaming_args": (
        "soothe_cli.tui.textual_adapter._stream_messages",
        "_defer_tool_card_for_empty_streaming_args",
    ),
    "_expand_nonstandard_tool_blocks": (
        "soothe_cli.tui.textual_adapter._stream_messages",
        "_expand_nonstandard_tool_blocks",
    ),
    "_format_progress_event_lines_for_tui": (
        "soothe_cli.tui.textual_adapter._stream_formatting",
        "_format_progress_event_lines_for_tui",
    ),
    "_format_task_scoped_tool_invocation_line": (
        "soothe_cli.tui.textual_adapter._stream_formatting",
        "_format_task_scoped_tool_invocation_line",
    ),
    "_handle_interrupt_cleanup": (
        "soothe_cli.tui.textual_adapter._turn_helpers",
        "_handle_interrupt_cleanup",
    ),
    "_mount_subagent_inner_tool_row_if_resolved": (
        "soothe_cli.tui.textual_adapter._stream_formatting",
        "_mount_subagent_inner_tool_row_if_resolved",
    ),
    "_tui_effective_ai_blocks": (
        "soothe_cli.tui.textual_adapter._stream_messages",
        "_tui_effective_ai_blocks",
    ),
    "_tui_goal_completion_matches_prior_main_visible_answer": (
        "soothe_cli.tui.textual_adapter._stream_messages",
        "_tui_goal_completion_matches_prior_main_visible_answer",
    ),
}


def __getattr__(name: str) -> Any:
    if name == "_repair_concatenated_output_text":
        from soothe_cli.shared.rendering.renderer_base import RendererBase

        fn = RendererBase.repair_concatenated_output
        globals()[name] = fn
        return fn
    spec = _LAZY_EXPORTS.get(name)
    if spec is not None:
        mod_path, attr = spec
        value = getattr(import_module(mod_path), attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(_LAZY_EXPORTS.keys()) | {"_repair_concatenated_output_text"})
