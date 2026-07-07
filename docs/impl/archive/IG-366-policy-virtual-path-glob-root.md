# IG-366: Policy alignment for virtual_mode paths and glob search root

## Problem

With `virtual_mode=True` (workspace sandbox), filesystem tools use virtual absolute paths such as `/README.md` mapped under the workspace. `WorkspaceToolOperationSecurity` treated those strings as host paths (`/README.md` → OS root), causing false denials. `glob` with only a `pattern` had no `target_path` for policy, so workspace containment was skipped.

## Approach

1. **`WorkspaceToolOperationSecurity._check_filesystem`**: When `allow_paths_outside_workspace` is false and a workspace is set, resolve some POSIX `/...` paths with `resolve_backend_os_path(..., virtual_mode=True)` before pattern and workspace-boundary checks so virtual tool paths match the filesystem backend. **Guard**: do not remap host-style absolutes whose first segment is a typical OS root name (`tmp`, `Users`, `etc`, …) when that path is not already under the workspace—so `glob` with `path=/tmp/outside` still denies (IG-300 test). On failure, fall back to `expand_path`.
2. **`extract_filesystem_path_for_policy`**: For `glob`, when `path` is missing or blank, return `"/"` as the synthetic virtual search root so policy runs the same containment logic.

## Verification

- Unit tests: `packages/soothe/tests/unit/core/security/`, `packages/soothe-sdk/tests/unit/utils/test_tool_meta.py`
- `./scripts/verify_finally.sh`
