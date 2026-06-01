"""Built-in subagents shipped with the core ``soothe`` package.

Importing this package registers curated ``soothe.subagent.*`` wire types from each
subagent's ``events`` module. Heavy delegates (``browser_use``, ``claude``) require
opt-in extras (``soothe[browser_use]``, ``soothe[claude]``) — their ``on_load`` hooks
verify the runtime dependency is installed.
"""

from .browser_use import events as _browser_use_events  # noqa: F401
from .claude import events as _claude_events  # noqa: F401
from .explore import events as _explore_events  # noqa: F401
from .tacitus import events as _tacitus_events  # noqa: F401

__all__: list[str] = []
