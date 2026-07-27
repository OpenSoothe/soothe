"""Minimal stdout-only renderer for headless CLI (IG-343).

Emits RFC-614 loop-tagged assistant text for the main graph (empty LangGraph namespace)
and loop-tagged finals (including replayed ``goal_completion`` from IG-355). Subgraph
namespaced prose is suppressed unless loop-tagged. Stderr is used for errors.

UI transcript SoT is ``soothe.card.*`` (TUI / appkit); headless keeps raw ``messages``
phases for stdout and does not project card frames.
"""

from __future__ import annotations

import sys
from typing import Any

from rich.console import Console

from soothe_cli.runtime.presentation.renderer_base import RendererBase


class HeadlessCliRenderer(RendererBase):
    """Headless mode: clean assistant output on stdout, errors on stderr."""

    def __init__(self) -> None:
        super().__init__()
        self.console = Console()

    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        if not is_main or task_scope:
            return
        payload = text if is_streaming else self.repair_concatenated_output(text)
        if not payload:
            return
        sys.stdout.write(payload)
        sys.stdout.flush()

    def on_streaming_output(
        self,
        event_type: str,
        text: str,
        *,
        is_chunk: bool,
        namespace: tuple[str, ...],
    ) -> None:
        self.on_assistant_text(text, is_main=True, is_streaming=is_chunk)

    def on_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        tool_call_id: str,
        *,
        is_main: bool,
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        del name, args, tool_call_id, is_main, task_scope

    def on_tool_result(
        self,
        name: str,
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        del name, result, tool_call_id, is_error, is_main, task_scope

    def on_status_change(self, state: str) -> None:
        del state

    def on_error(self, error: str, *, context: str | None = None) -> None:
        prefix = f"[{context}] " if context else ""
        sys.stderr.write(f"{prefix}ERROR: {error}\n")
        sys.stderr.flush()

    def on_progress_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        namespace: tuple[str, ...],
        task_scope: tuple[str, str] | None = None,
    ) -> None:
        del event_type, data, namespace, task_scope

    def on_plan_created(self, plan: Any) -> None:
        del plan

    def on_turn_end(self) -> None:
        """End of turn; headless does not append synthetic newlines to stdout."""
