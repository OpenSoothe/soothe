"""Workspace resolution and path policy helpers."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from soothe_sdk.utils import INVALID_WORKSPACE_DIRS

logger = logging.getLogger(__name__)

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
    """Build ``ws_<hash>`` from ``user_id`` and a scope key."""
    uid = user_id_for_hash(user_id)
    key = f"{uid}:{scope_key}"
    hash_hex = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"ws_{hash_hex}"


def _validate_workspace_dir(path: Path) -> None:
    path_str = str(path.resolve())
    if path_str in INVALID_WORKSPACE_DIRS:
        msg = f"Invalid workspace: {path} is a system directory. Set SOOTHE_WORKSPACE env var."
        raise ValueError(msg)


def validate_client_workspace(workspace: str | Path) -> Path:
    """Validate and resolve client-provided workspace."""
    original_path = Path(workspace)
    path = original_path.expanduser().resolve()
    original_str = str(original_path)
    resolved_str = str(path)
    if original_str in INVALID_WORKSPACE_DIRS or resolved_str in INVALID_WORKSPACE_DIRS:
        msg = (
            f"Invalid client workspace: {workspace} is a system directory. "
            "Please run from a project directory."
        )
        raise ValueError(msg)
    if not path.exists():
        logger.debug("Client workspace does not exist: %s", path)
    return path


def translate_client_path_to_container(
    client_path: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
) -> Path:
    """Translate a client-side path to its container-side equivalent."""
    if not host_root or not container_root:
        return Path(client_path).resolve()
    host = Path(host_root).resolve()
    container = Path(container_root).resolve()
    resolved = Path(client_path).resolve()
    try:
        relative = resolved.relative_to(host)
    except ValueError:
        msg = (
            f"Client workspace {resolved} is not under configured host_root {host}. "
            "All workspaces must reside under the configured host_root for container deployments."
        )
        raise ValueError(msg) from None
    return container / relative


def translate_container_path_to_client(
    container_path: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
) -> Path:
    """Translate a container-side path to its client-side equivalent."""
    if not host_root or not container_root:
        return Path(container_path).resolve()
    host = Path(host_root).resolve()
    container = Path(container_root).resolve()
    resolved = Path(container_path).resolve()
    try:
        relative = resolved.relative_to(container)
    except ValueError:
        return resolved
    return host / relative


def _coerce_workspace(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return None


def _workspace_from_configurable(configurable: Any) -> Path | None:
    if not isinstance(configurable, dict):
        return None
    return _coerce_workspace(configurable.get("workspace"))


def _workspace_from_messages(messages: Any) -> Path | None:
    if not isinstance(messages, (list, tuple)):
        return None
    for msg in reversed(messages):
        ws = _coerce_workspace(getattr(msg, "workspace", None))
        if ws is not None:
            return ws
        if isinstance(msg, dict):
            additional = msg.get("additional_kwargs")
            if isinstance(additional, dict):
                ws = _coerce_workspace(additional.get("workspace"))
                if ws is not None:
                    return ws
            ws = _coerce_workspace(msg.get("workspace"))
            if ws is not None:
                return ws
    return None


def _workspace_from_state_dict(state: dict[str, Any] | None) -> Path | None:
    if not isinstance(state, dict):
        return None
    direct = _coerce_workspace(state.get("workspace"))
    if direct is not None:
        return direct
    return _workspace_from_messages(state.get("messages"))


def _runtime_config(runtime: Any) -> dict[str, Any] | None:
    cfg = getattr(runtime, "config", None)
    return cfg if isinstance(cfg, dict) else None


def _runtime_state(runtime: Any) -> dict[str, Any] | None:
    state = getattr(runtime, "state", None)
    return state if isinstance(state, dict) else None


def resolve_workspace_for_tool_execution(
    *,
    runtime: Any | None = None,
    config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    fallback: str | Path | None = None,
    use_langgraph_config: bool = True,
) -> Path | None:
    """Resolve effective workspace for the current tool or agent turn."""
    effective_config = config if config is not None else _runtime_config(runtime)
    effective_state = state if state is not None else _runtime_state(runtime)

    if isinstance(effective_config, dict):
        ws = _workspace_from_configurable(effective_config.get("configurable"))
        if ws is not None:
            return ws

    ws = _workspace_from_state_dict(effective_state)
    if ws is not None:
        return ws

    if use_langgraph_config:
        try:
            from langgraph.config import get_config

            lg_config = get_config()
            if isinstance(lg_config, dict):
                ws = _workspace_from_configurable(lg_config.get("configurable"))
                if ws is not None:
                    return ws
        except Exception:  # noqa: S110
            pass

    from soothe_nano.workspace.workspace_runtime import get_workspace_context

    current = get_workspace_context().workspace
    if current is not None:
        return current

    return _coerce_workspace(fallback)
