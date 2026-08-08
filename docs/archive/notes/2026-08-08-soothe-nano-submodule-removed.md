# soothe-nano submodule removed from monorepo (2026-08-08)

The `packages/soothe-nano` git submodule was removed from this repository.
Soothe now consumes Coding CoreAgent exclusively as the PyPI package
`soothe-nano` (pin in `packages/soothe/pyproject.toml`).

## Removed from tree

| Item | Notes |
|------|--------|
| Submodule `packages/soothe-nano` | Was `git@github.com:mirasoth/soothe-nano.git` |
| Workspace source `soothe-nano = { workspace = true }` | Resolve from PyPI instead |

## Follow-on wiring

| Item | Change |
|------|--------|
| `scripts/build_runtime_requirements.py` | Keep `soothe-nano` pin from host deps; no local nano pyproject |
| `packages/soothe-daemon/Dockerfile.local` | Install nano from PyPI; do not COPY nano sources |
| `.github/workflows/release.yml` | Wait for nano floor from `packages/soothe/pyproject.toml` |

The external `mirasoth/soothe-nano` repository is unchanged and remains the
release home for `soothe-nano`.
