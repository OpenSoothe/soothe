# IG-300: virtual_mode host-absolute path normalization

## Problem

With `virtual_mode=True`, deepagents `FilesystemBackend._resolve_path` treats any path starting with `/` as a **virtual** path under the workspace root (`root_dir / key.lstrip("/")`). Tools that pass a real host path (e.g. `/Users/me/project/file.py`) while the workspace is that project resolve to `workspace/Users/me/project/...`, which does not exist. `read`, `write`, `edit`, `grep_raw`, etc. use `_resolve_path` directly; only `ls_info` / `glob_info` on `NormalizedPathBackend` pre-normalized paths.

## Approach

1. **`NormalizedPathBackend._normalize_path`**: When `virtual_mode=True` and the expanded absolute path lies under the workspace, return a virtual path `"/" + relative.as_posix()` instead of the raw host absolute string.
2. **`NormalizedPathBackend._resolve_path`**: Prepend normalization so every inherited operation gets consistent resolution.
3. **`WorkspaceAwareBackend._normalize_path`**: Mirror the in-workspace + `virtual_mode` branch so `ls` / `als` / `glob_info` wrappers that pre-normalize pass virtual paths into the backend.

## Verification

- Unit tests in `packages/soothe/tests/unit/core/workspace/`
- `./scripts/verify_finally.sh`
