# IG-300: Workspace isolation and security policy alignment

**Status**: Completed  
**Scope**: Daemon/workspace isolation, path normalization, `ConfigDrivenPolicy` alignment with real deepagents tool names, per-loop daemon workspace fallback, subagent alignment with `security.allow_paths_outside_workspace`, unified tool metadata for policy/path extraction.

## Decisions

1. **Strict default**: Template `config.yml` and Pydantic `SecurityConfig` default `allow_paths_outside_workspace` to `false` (secure-by-default). Dev overlay documents the same `security:` block.
2. **Effective workspace for policy**: `PolicyContext.workspace` (optional) carries the absolute workspace string from LangGraph `configurable["workspace"]` when present; `ConfigDrivenPolicy` uses it for boundary checks before falling back to `config.workspace_dir`.
3. **Per-loop daemon workspace**: `resolve_loop_daemon_workspace(loop_id)` → `$SOOTHE_HOME/Workspace/<loop_id>/`, validated and created once per loop; `loop_input` (and `loop_new` pre-touch) bind the execution thread’s registry workspace to that path instead of the global daemon default.
4. **Path normalization**: `~` expanded in `NormalizedPathBackend._normalize_path`; shared helpers in `core/workspace/path_normalization.py` for unit tests and strict resolved-path checks.
5. **Policy + metadata**: Filesystem boundary and deny/allow stages use `soothe_sdk.tools.metadata` (`is_policy_filesystem_tool`, `extract_filesystem_path_for_policy`) instead of `fs_*` prefixes and `file_path`-only extraction.
6. **Subagents**: Explore uses `virtual_mode = not allow_paths_outside_workspace`. Research `FilesystemSource` sets `allow_outside_workdir` from the same flag. Claude plugin defaults `permission_mode` to `plan` when outside paths are disallowed unless overridden in kwargs.

## Test checklist

- [x] `strict_workspace_path` unit tests (containment / escape / empty).
- [x] `ConfigDrivenPolicy`: `glob` / `read_file` outside workspace, approval path, whitelist denial, `file_path` extraction.
- [x] `resolve_loop_daemon_workspace`: creates directory, rejects unsafe `loop_id`.
- [x] Metadata helpers: `is_policy_filesystem_tool` / `extract_filesystem_path_for_policy` (SDK tests).
- [x] `./scripts/verify_finally.sh` passes (mandatory before merge).

## References

- Plan: workspace security hardening (attached IG-300 plan, not edited in-repo).
- `packages/soothe/src/soothe/core/workspace/backend.py`
- `packages/soothe/src/soothe/core/persistence/config_policy.py`
- `packages/soothe-sdk/src/soothe_sdk/tools/metadata.py`
