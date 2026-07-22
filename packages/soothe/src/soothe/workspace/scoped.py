"""Filesystem-safe workspace directory naming helpers."""

from __future__ import annotations

import hashlib
import re

_ANONYMOUS_USER_DIR = "anonymous"
_WS_DIR_PATTERN = re.compile(r"[^\w\-.@]+")


def normalize_user_id(user_id: str | None) -> str:
    """Return a filesystem-safe directory segment for workspace layout."""
    if not user_id or not str(user_id).strip():
        return _ANONYMOUS_USER_DIR
    safe = _WS_DIR_PATTERN.sub("_", str(user_id).strip())
    return safe or _ANONYMOUS_USER_DIR


def user_id_for_hash(user_id: str | None) -> str:
    """User id string used inside workspace hash keys (empty when anonymous)."""
    if not user_id or not str(user_id).strip():
        return ""
    return str(user_id).strip()


def compute_scoped_workspace_dir_name(user_id: str | None, scope_key: str) -> str:
    """Build ``ws_<hash>`` from ``user_id`` and a workspace scope key."""
    uid = user_id_for_hash(user_id)
    key = f"{uid}:{scope_key}"
    hash_hex = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"ws_{hash_hex}"


__all__ = [
    "compute_scoped_workspace_dir_name",
    "normalize_user_id",
    "user_id_for_hash",
]
