"""Loop-scoped workspace resolution for daemon runs and ``LoopRunRequest``."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from soothe.foundation.workspace.resolution import validate_client_workspace

logger = logging.getLogger(__name__)

_ANONYMOUS_USER_DIR = "anonymous"
_WS_DIR_PATTERN = re.compile(r"[^\w\-.@]+")


def normalize_user_id(user_id: str | None) -> str:
    """Return a filesystem-safe directory segment for workspace layout.

    Empty or whitespace-only ``user_id`` maps to ``anonymous``.
    """
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
    """Build ``ws_<hash>`` from ``user_id`` (or empty) and a scope key.

    Args:
        user_id: Raw user id; empty/None uses empty string in the hash.
        scope_key: ``client_workspace_id`` or ``loop_id`` when no client path.
    """
    uid = user_id_for_hash(user_id)
    key = f"{uid}:{scope_key}"
    hash_hex = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"ws_{hash_hex}"


def resolve_persisted_loop_workspace(
    *,
    loop_id: str,
    user_id: str | None = None,
    client_workspace_id: str | None = None,
    soothe_home: Path | None = None,
    create: bool = True,
) -> Path:
    """Resolve ``$SOOTHE_HOME/data/workspaces/<user>/ws_<hash>`` when no client path.

    Args:
        loop_id: Loop identifier (hash scope when ``client_workspace_id`` unset).
        user_id: Optional user id (empty → ``anonymous`` dir + empty hash prefix).
        client_workspace_id: Optional stable workspace scope for the user.
        soothe_home: Override for tests.
        create: Create directory when missing.
    """
    from soothe.config import SOOTHE_HOME

    normalized_user = normalize_user_id(user_id)
    scope = (
        str(client_workspace_id).strip()
        if client_workspace_id and str(client_workspace_id).strip()
        else str(loop_id).strip()
    )
    if not scope:
        msg = "loop_id is required for persisted workspace resolution"
        raise ValueError(msg)

    ws_name = compute_scoped_workspace_dir_name(user_id, scope)
    home = Path(soothe_home or SOOTHE_HOME).expanduser().resolve()
    workspace_path = home / "data" / "workspaces" / normalized_user / ws_name

    if create:
        workspace_path.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Resolved persisted loop workspace: user=%s scope=%s -> %s",
            normalized_user,
            scope[:32],
            workspace_path,
        )

    return workspace_path


def resolve_loop_workspace(
    *,
    loop_id: str,
    client_workspace: str | Path | None = None,
    user_id: str | None = None,
    client_workspace_id: str | None = None,
    soothe_home: Path | None = None,
    create: bool = True,
) -> Path:
    """Resolve the workspace directory for a loop run.

    Precedence:
        1. ``client_workspace`` — use the validated client path directly.
        2. Persisted layout — ``$SOOTHE_HOME/data/workspaces/<normalized_user>/ws_<hash>``
           where hash is ``sha256(user_id, client_workspace_id)`` or
           ``sha256(user_id, loop_id)`` when ``client_workspace_id`` is unset.
           ``user_id`` empty uses ``anonymous`` as the directory segment and ``""``
           in the hash key.
    """
    client_ws = str(client_workspace).strip() if client_workspace else None
    if client_ws:
        path = validate_client_workspace(client_ws)
        if path.exists():
            return path
        logger.warning(
            "Client workspace not present on daemon host (%s); using persisted layout",
            path,
        )

    return resolve_persisted_loop_workspace(
        loop_id=loop_id,
        user_id=user_id,
        client_workspace_id=client_workspace_id,
        soothe_home=soothe_home,
        create=create,
    )
