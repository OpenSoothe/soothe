"""Clarification relay: policies, interrupt detection, and the tool-approval pipeline.

Public surface: the two clarification policies and their entry points. The
auto policy pulls in the veritas subagent chain, so all symbols are imported
lazily via `__getattr__` — importing a light submodule (`clarification.origins`,
`clarification.protocol`) does not trigger the full dependency chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.sloop.clarification.auto import AutoClarificationPolicy
    from soothe.sloop.clarification.detector import ClarificationDetector
    from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy
    from soothe.sloop.clarification.tool_approval_pipeline import ToolApprovalPipeline

__all__ = [
    "AutoClarificationPolicy",
    "ClarificationDetector",
    "InteractiveClarificationPolicy",
    "ToolApprovalPipeline",
]


def __getattr__(name: str) -> Any:
    if name == "AutoClarificationPolicy":
        from soothe.sloop.clarification import auto as _auto_mod

        return _auto_mod.AutoClarificationPolicy
    if name == "ClarificationDetector":
        from soothe.sloop.clarification import detector as _detector_mod

        return _detector_mod.ClarificationDetector
    if name == "InteractiveClarificationPolicy":
        from soothe.sloop.clarification import interactive as _interactive_mod

        return _interactive_mod.InteractiveClarificationPolicy
    if name == "ToolApprovalPipeline":
        from soothe.sloop.clarification import tool_approval_pipeline as _pipeline_mod

        return _pipeline_mod.ToolApprovalPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
