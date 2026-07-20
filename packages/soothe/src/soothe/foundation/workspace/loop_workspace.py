"""Loop-scoped workspace resolution for daemon runs and ``LoopRunRequest``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from soothe_nano.workspace.resolution import (
    translate_client_path_to_container,
    validate_client_workspace,
)
from soothe_nano.workspace.scoped import (
    compute_scoped_workspace_dir_name,
    normalize_user_id,
    user_id_for_hash,
)

__all__ = [
    "compute_scoped_workspace_dir_name",
    "normalize_user_id",
    "resolve_loop_workspace",
    "resolve_persisted_loop_workspace",
    "user_id_for_hash",
]

logger = logging.getLogger(__name__)


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
        from soothe.config import DEFAULT_CONFIG_PATH, SootheConfig

        cfg_path = Path(DEFAULT_CONFIG_PATH).expanduser()
        if not cfg_path.exists():
            return None, None
        mount = SootheConfig.from_yaml_file(str(cfg_path)).workspace_mount
        if mount.is_configured:
            return mount.host_root, mount.container_root
    except Exception as exc:
        logger.debug("Could not load workspace_mount from config: %s", exc)
    return None, None


def _resolve_mount_roots(
    *,
    workspace_mapping: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Resolve RFC-621 mount roots from loop metadata or config."""
    hr: str | None = None
    cr: str | None = None
    if workspace_mapping:
        raw = workspace_mapping.get("host_root")
        hr = str(raw).strip() if raw else None
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
    workspace_mapping: dict[str, Any] | None = None,
) -> Path | None:
    """Resolve a client workspace hint to a usable path on this host/container.

    Returns the path when it exists locally or maps under ``workspace_mount``.
    """
    path = validate_client_workspace(client_workspace)

    hr, cr = _resolve_mount_roots(workspace_mapping=workspace_mapping)
    if hr and cr:
        try:
            translated = translate_client_path_to_container(
                path,
                host_root=hr,
                container_root=cr,
            )
        except ValueError:
            translated = None
        if translated is not None and translated.exists():
            logger.info(
                "Resolved client workspace via mount mapping: %s -> %s",
                path,
                translated,
            )
            return translated

    if path.exists():
        return path

    return None


def resolve_loop_workspace(
    *,
    loop_id: str,
    client_workspace: str | Path | None = None,
    user_id: str | None = None,
    client_workspace_id: str | None = None,
    soothe_home: Path | None = None,
    create: bool = True,
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
