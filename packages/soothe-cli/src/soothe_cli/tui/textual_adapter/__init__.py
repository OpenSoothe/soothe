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

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
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
    "execute_task_textual": ("soothe_cli.tui.textual_adapter._turn", "execute_task_textual"),
    "print_usage_table": ("soothe_cli.tui.textual_adapter._stream_formatting", "print_usage_table"),
    "_expand_nonstandard_tool_blocks": (
        "soothe_cli.tui.textual_adapter._stream_messages",
        "_expand_nonstandard_tool_blocks",
    ),
    "_handle_interrupt_cleanup": (
        "soothe_cli.tui.textual_adapter._turn_helpers",
        "_handle_interrupt_cleanup",
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
        from soothe_cli.events.rendering.renderer_base import RendererBase

        fn = RendererBase.repair_concatenated_output
        globals()[name] = fn
        return fn
    if name in _LAZY_EXPORTS:
        module_path, attr = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_path), attr)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
