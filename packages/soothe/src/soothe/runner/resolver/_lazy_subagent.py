"""Host re-export of nano deferred subagent compilation.

Canonical implementation lives in ``soothe_nano.resolve._lazy_subagent``.
"""

from __future__ import annotations

from soothe_nano.resolve._lazy_subagent import (
    LazySubagentRunnable,
    lazy_compiled_subagent_spec,
    subagent_description,
)

__all__ = [
    "LazySubagentRunnable",
    "lazy_compiled_subagent_spec",
    "subagent_description",
]
