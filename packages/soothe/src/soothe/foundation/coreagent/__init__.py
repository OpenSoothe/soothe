"""CoreAgent runtime package.

Runtime implementations live under ``coreagent``. The default implementation is
``CodingCoreAgent`` in ``coreagent.coding``.
"""

from soothe.foundation.coreagent.coding import (
    AgentBuilder,
    CodingCoreAgent,
    LazyCoreAgent,
    create_soothe_agent,
)

__all__ = [
    "AgentBuilder",
    "CodingCoreAgent",
    "LazyCoreAgent",
    "create_soothe_agent",
]
