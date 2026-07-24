"""Host aliases for shared prompt-clock helpers.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.utils.prompt_clock``.  Do not duplicate or modify the
re-exported symbols here; fix them in nano.
"""

# Re-export facade — canonical source: soothe_nano.utils.prompt_clock
from soothe_nano.utils.prompt_clock import (
    local_date_str,
    local_time_str,
    local_timestamp_iso,
    local_timezone_label,
    now_local,
    prompt_datetime_context,
)

__all__ = [
    "local_date_str",
    "local_time_str",
    "local_timestamp_iso",
    "local_timezone_label",
    "now_local",
    "prompt_datetime_context",
]
