"""Host aliases for shared text-preview helpers.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.utils.text_preview``.  Do not duplicate or modify the
re-exported symbols here; fix them in nano.
"""

# Re-export facade — canonical source: soothe_nano.utils.text_preview
from soothe_nano.utils.text_preview import (
    create_output_summary,
    goal_description_for_log,
    log_preview,
    preview,
    preview_first,
)

__all__ = [
    "create_output_summary",
    "goal_description_for_log",
    "log_preview",
    "preview",
    "preview_first",
]
