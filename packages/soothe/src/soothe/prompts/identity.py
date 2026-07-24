"""Host alias for shared assistant identity prompt helpers.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.prompts.identity``.  Do not duplicate or modify the
re-exported symbols here; fix them in nano.
"""

# Re-export facade — canonical source: soothe_nano.prompts.identity
from soothe_nano.prompts.identity import (
    build_assistant_identity_block,
    normalize_assistant_name,
    prepend_assistant_identity,
)

__all__ = [
    "build_assistant_identity_block",
    "normalize_assistant_name",
    "prepend_assistant_identity",
]
