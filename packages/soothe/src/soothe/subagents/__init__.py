"""Built-in subagents shipped with the core ``soothe`` package.

Optional heavy delegates are published in ``soothe-community`` (separate install).
Importing this package registers curated ``soothe.subagent.*`` wire types from each
subagent's ``events`` module.
"""

from .explore import events as _explore_events  # noqa: F401
from .tacitus import events as _tacitus_events  # noqa: F401

__all__: list[str] = []
