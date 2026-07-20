"""Built-in CoreAgent subagents (soothe-nano).

Veritas lives in ``soothe.subagents.veritas`` (host clarification relay).
"""

from .academic_research import events as _academic_research_events  # noqa: F401
from .browser_use import events as _browser_use_events  # noqa: F401
from .deep_research import events as _deep_research_events  # noqa: F401
from .explore import events as _explore_events  # noqa: F401

__all__: list[str] = []
