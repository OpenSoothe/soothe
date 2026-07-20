"""Host alias for shared assistant identity prompt helpers."""

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
