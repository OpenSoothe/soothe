"""Loop-scoped workspace resolution for daemon runs and ``LoopRunRequest``."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from soothe.foundation.workspace.resolution import (
    translate_client_path_to_container,
    validate_client_workspace,
)

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


def _workspace_mount_from_config() -> tuple[str | None, str | None]:
    """Return configured ``workspace_mount`` host/container roots when set."""
    try:
        from soothe.config import get_config

        mount = get_config().workspace_mount
        if mount.is_configured:
            return mount.host_root, mount.container_root
    except Exception:
        logger.debug("Could not load workspace_mount from config", exc_info=True)
    return None, None


def _resolve_mount_roots(
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
    workspace_mapping: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Resolve RFC-621 mount roots from explicit args, metadata, or config."""
    hr = str(host_root).strip() if host_root else None
    cr = str(container_root).strip() if container_root else None
    if workspace_mapping:
        if not hr:
            raw = workspace_mapping.get("host_root")
            hr = str(raw).strip() if raw else None
        if not cr:
            raw = workspace_mapping.get("container_root")
            cr = str(raw).strip() if raw else None
    if not hr or not cr:
        cfg_hr, cfg_cr = _workspace_mount_from_config()
        hr = hr or cfg_hr
        cr = cr or cfg_cr
    return hr, cr


def resolve_client_workspace_on_host(
    client_workspace: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
    workspace_mapping: dict[str, Any] | None = None,
) -> Path | None:
    """Resolve a client workspace hint to a usable path on this host/container.

    Returns the path when it exists locally or maps under ``workspace_mount``.
    """
    path = validate_client_workspace(client_workspace)
    if path.exists():
        return path

    hr, cr = _resolve_mount_roots(
        host_root=host_root,
        container_root=container_root,
        workspace_mapping=workspace_mapping,
    )
    if not hr or not cr:
        return None

    try:
        translated = translate_client_path_to_container(
            path,
            host_root=hr,
            container_root=cr,
        )
    except ValueError:
        return None

    if translated.exists():
        logger.info(
            "Resolved client workspace via mount mapping: %s -> %s",
            path,
            translated,
        )
        return translated
    return None


def resolve_loop_workspace(
    *,
    loop_id: str,
    client_workspace: str | Path | None = None,
    user_id: str | None = None,
    client_workspace_id: str | None = None,
    soothe_home: Path | None = None,
    create: bool = True,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
    workspace_mapping: dict[str, Any] | None = None,
) -> Path:
    """Resolve the workspace directory for a loop run.

    Precedence:
        1. ``client_workspace`` — use the validated client path directly, or map it
           via ``workspace_mount`` when the host path is absent on this machine.
        2. Persisted layout — ``$SOOTHE_HOME/data/workspaces/<normalized_user>/ws_<hash>``
           where hash is ``sha256(user_id, client_workspace_id)`` or
           ``sha256(user_id, loop_id)`` when ``client_workspace_id`` is unset.
           ``user_id`` empty uses ``anonymous`` as the directory segment and ``""``
           in the hash key.
    """
    client_ws = str(client_workspace).strip() if client_workspace else None
    if client_ws:
        resolved = resolve_client_workspace_on_host(
            client_ws,
            host_root=host_root,
            container_root=container_root,
            workspace_mapping=workspace_mapping,
        )
        if resolved is not None:
            return resolved
        logger.warning(
            "Client workspace not present on daemon host (%s); using persisted layout",
            validate_client_workspace(client_ws),
        )

    return resolve_persisted_loop_workspace(
        loop_id=loop_id,
        user_id=user_id,
        client_workspace_id=client_workspace_id,
        soothe_home=soothe_home,
        create=create,
    )
