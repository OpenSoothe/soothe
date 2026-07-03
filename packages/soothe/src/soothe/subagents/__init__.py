"""Built-in subagents shipped with the core ``soothe`` package.

Importing this package registers curated ``soothe.subagent.*`` wire types from each
subagent's ``events`` module. ``browser_use`` ships with core dependencies; its
``on_load`` hook still verifies that runtime dependencies are installed.
"""

from .browser_use import events as _browser_use_events  # noqa: F401
from .skillify import events as _skillify_events  # noqa: F401
from .tacitus import events as _tacitus_events  # noqa: F401

__all__: list[str] = []
