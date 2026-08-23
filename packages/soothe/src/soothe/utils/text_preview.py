"""Host aliases for shared text-preview helpers.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.utils.text_preview``.  Do not duplicate or modify the
re-exported symbols here; fix them in nano.
"""

# Re-export facade — canonical source: soothe_nano.utils.text_preview
from soothe_nano.utils.text_preview import (
    goal_description_for_log,
)

__all__ = [
    "goal_description_for_log",
]
