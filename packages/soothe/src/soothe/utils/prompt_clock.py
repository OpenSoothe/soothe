"""Host aliases for shared prompt-clock helpers."""

# Re-export facade — canonical source: soothe_nano.utils.prompt_clock
from soothe_nano.utils.prompt_clock import (
    local_date_str,
    local_timezone_label,
    prompt_datetime_context,
)

__all__ = [
    "local_date_str",
    "local_timezone_label",
    "prompt_datetime_context",
]
