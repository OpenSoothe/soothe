# IG-316: virtual_mode for path tools (excluding shell)

## Status

Completed.

## Goal

Align surgical filesystem tools, resolver-built backends, FileOps plugin, and data/image/audio/video local-path tools with `FilesystemBackend` / `NormalizedPathBackend` path semantics (`virtual_mode = not security.allow_paths_outside_workspace`), matching `FrameworkFilesystem`. Shell / execution tools are unchanged (future sandbox).

## Scope

- New helper `resolve_backend_os_path` (and related config helpers) under `soothe.core.workspace`.
- `_resolver_tools.py` file_ops branches.
- `SootheFilesystemMiddleware` surgical tools + `apply_diff` target path.
- `FileOpsPlugin.on_load` defaults from `soothe_config`.
- Data / image / audio / video toolkits for local paths only.

## Verification

- Unit tests for resolver/middleware and at least one data path case.
- `./scripts/verify_finally.sh`

## References

- IG-300 workspace security
- `FrameworkFilesystem.initialize` virtual_mode formula
