"""Build wire-safe model catalog payloads from ``SootheConfig`` (daemon + tools).

Used by the daemon WebSocket ``models_list`` RPC so clients list the same
models declared on the server host's configuration, without reading the
client's ``config.yml``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_IMPLICIT_AUTH: frozenset[str] = frozenset({"google_vertexai", "ollama"})


def _provider_has_credentials(cfg: SootheConfig, provider_name: str) -> bool | None:
    """Return whether the provider appears credentialed on the daemon host."""
    if not provider_name:
        return None
    p = cfg._find_provider(provider_name)  # noqa: SLF001
    if p is None:
        return None
    if p.provider_type in _IMPLICIT_AUTH or p.provider_type == "ollama":
        if p.provider_type == "google_vertexai":
            proj = os.getenv("SOOTHE_GOOGLE_CLOUD_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
            return bool(proj.strip())
        return None
    if p.api_key:
        try:
            from soothe.config.env import _resolve_provider_env

            v = _resolve_provider_env(p.api_key, provider_name=p.name, field_name="api_key")
        except Exception:
            logger.debug("resolve api_key failed for provider %r", provider_name, exc_info=True)
            return None
        return bool(v and str(v).strip())
    return False


def build_models_list_payload(cfg: SootheConfig) -> dict[str, Any]:
    """Return JSON-serializable catalog for ``models_list_response``.

    Args:
        cfg: Loaded daemon ``SootheConfig``.

    Returns:
        Dict with ``models`` (list of rows) and ``default_model`` (``provider:model`` or ``None``).
    """
    rows: list[dict[str, Any]] = []
    for p in cfg.providers or []:
        has_creds = _provider_has_credentials(cfg, p.name)
        if p.models:
            for m in p.models:
                rows.append(
                    {
                        "spec": f"{p.name}:{m}",
                        "provider": p.name,
                        "model": m,
                        "has_credentials": has_creds,
                    },
                )
        else:
            rows.append(
                {
                    "spec": "",
                    "provider": p.name,
                    "model": "",
                    "has_credentials": has_creds,
                    "placeholder": True,
                },
            )

    default_model: str | None = None
    try:
        default_model = cfg.resolve_model("default")
    except Exception:
        logger.debug("Could not resolve default model for catalog", exc_info=True)

    return {"models": rows, "default_model": default_model}
