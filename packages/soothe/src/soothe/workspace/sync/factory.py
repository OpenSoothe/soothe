"""Factory for constructing `WorkspaceSyncBackend` instances from URIs.

The `construct_sync_backend` factory is the entry point for creating a
workspace sync backend from a user-supplied URI (e.g.
`s3://bucket/pfx`).  Only remote object-store schemes (`s3`, `gs`,
`az`) are permitted from user input to prevent SSRF / local file read.
The fsspec global filesystem cache is disabled to prevent credential
leakage to the agent process.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.workspace.sync.backends.fsspec import FsspecSyncBackend

if TYPE_CHECKING:
    from soothe_sdk.protocols.workspace_sync import WorkspaceSyncBackend

logger = logging.getLogger(__name__)

_ALLOWED_SYNC_SCHEMES: frozenset[str] = frozenset({"s3", "gs", "az"})


def construct_sync_backend(
    uri: str,
    config: dict[str, Any] | None = None,
) -> WorkspaceSyncBackend:
    """Construct a `WorkspaceSyncBackend` from a URI.

    Uses `fsspec.url_to_fs(uri)` to resolve the filesystem — no
    per-scheme dispatch code needed.  The scheme allowlist is enforced
    before fsspec is called.

    Args:
        uri: Storage URI (e.g. `s3://bucket/prefix`,
            `gs://bucket/prefix`, `az://container/prefix`).
        config: Optional storage configuration (credentials, endpoint,
            etc.).  Prefer environment variables / IAM roles over
            explicit credential dicts.

    Returns:
        A `FsspecSyncBackend` instance backed by the resolved
        filesystem.

    Raises:
        ValueError: If the URI scheme is not in the allowlist, or if
            the URI is malformed.
    """
    scheme = _extract_scheme(uri)
    if scheme not in _ALLOWED_SYNC_SCHEMES:
        raise ValueError(
            f"unsupported workspace_sync_source scheme: {scheme!r}. "
            f"Allowed: {sorted(_ALLOWED_SYNC_SCHEMES)}"
        )

    import fsspec

    storage_options = _resolve_storage_options(uri, config)

    fs, root = fsspec.url_to_fs(uri, **storage_options)
    fs.use_cache = False

    logger.info(
        "Constructed FsspecSyncBackend: scheme=%s, root=%s, fs=%s",
        scheme,
        root,
        type(fs).__name__,
    )

    return FsspecSyncBackend(fs=fs, root=root)


def _extract_scheme(uri: str) -> str:
    """Extract the lowercased scheme from a URI.

    Args:
        uri: The URI to parse.

    Returns:
        The lowercased scheme (e.g. `"s3"`).

    Raises:
        ValueError: If the URI has no scheme.
    """
    if "://" not in uri:
        raise ValueError(f"URI has no scheme: {uri!r}")
    return uri.split("://", 1)[0].lower()


def _resolve_storage_options(
    uri: str,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve storage options from config.

    Prefer environment variables / IAM roles over explicit credential
    dicts.  Only explicitly recognized keys are passed through to
    fsspec to prevent injection of unexpected options.

    Args:
        uri: The storage URI (unused, reserved for future
            scheme-specific resolution).
        config: Optional configuration dict.

    Returns:
        A dict of storage options for fsspec.
    """
    del uri

    if config is None:
        return {}

    allowed_keys = frozenset(
        {
            "endpoint_url",
            "profile",
            "region_name",
            "key",
            "secret",
            "token",
            "anon",
            "project",
            "account_name",
            "account_key",
            "connection_string",
        }
    )

    return {k: v for k, v in config.items() if k in allowed_keys}
