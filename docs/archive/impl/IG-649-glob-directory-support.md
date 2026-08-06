# IG-649: High-performance directory-capable glob

**Status**: Migrated upstream  
**Package**: `soothe-deepagents` (engine) + `soothe-nano` (workspace adapter)  
**Related**: IG-570 (glob discovery hints)

## Goal

Allow the CoreAgent `glob` tool to return directories (e.g. `packages/*/`) without relying on `git ls-files`, using a fast `fd` path and a universal `os.scandir` fallback — same optional-binary pattern as `rg` for grep.

## Design

- **Upstream** (`soothe_deepagents.backends.glob_search` + `FilesystemBackend.glob`):
  - Tier 1: `fd` / `fdfind` (`DEEPAGENTS_FD_PATH` / `SOOTHE_FD_PATH` or PATH)
  - Tier 2: recursive `os.scandir` + pattern depth bound + wall-clock deadline
  - Trailing `/` ⇒ directories only; default files-only; `include_dirs=True` for files+dirs
- **Upstream grep** (`backends.grep_search`): `ripgrep_search` / `python_search` + `get_rg_bin` / `is_rg_available` / `reset_rg_bin_cache`; `FilesystemBackend` thin-wraps and re-exports probes
- **Nano** imports deepagents helpers directly (`glob_search` / filesystem re-exports); workspace keeps gitignore / host-absolute paths / result cap. Thin nano shims removed (`SOOTHE_RG_PATH` honored in deepagents).

## Touch points

- `soothe-deepagents/soothe_deepagents/backends/glob_search.py`
- `soothe-deepagents/soothe_deepagents/backends/grep_search.py`
- `soothe-deepagents/soothe_deepagents/backends/filesystem.py` (`glob`, thin `ripgrep_search` / `python_search`, probe re-exports)
- `soothe-nano/.../filesystem/workspace.py` / `local.py` (direct deepagents imports)
- `soothe-nano/.../filesystem/discovery_hints.py`
- Removed: `soothe-nano/.../filesystem/glob_search.py`, `grep_search.py`
