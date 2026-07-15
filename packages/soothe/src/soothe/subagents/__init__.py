"""Built-in subagents shipped with the core ``soothe`` package.

Importing this package registers curated ``soothe.subagent.*`` wire types from each
subagent's ``events`` module. ``browser_use`` ships with core dependencies; its
``on_load`` hook still verifies that runtime dependencies are installed.
"""

from .academic_research import events as _academic_research_events  # noqa: F401
from .browser_use import events as _browser_use_events  # noqa: F401
from .deep_research import events as _deep_research_events  # noqa: F401
from .explore import events as _explore_events  # noqa: F401
from .veritas import events as _veritas_events  # noqa: F401

__all__: list[str] = []
