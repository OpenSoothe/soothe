# IG-644: Extract soothe-plugins as submodule

**Guide**: IG-644
**Created**: 2026-07-22
**Related**: IG-625 (nano extract), IG-643 (weaver self-register landed in plugins tree)
**Status**: COMPLETE

## Summary

Moved `packages/soothe-plugins` from an in-tree monorepo package to a git
submodule at [mirasoth/soothe-plugins](https://github.com/mirasoth/soothe-plugins),
matching `soothe-sdk` / `soothe-nano`.

## Changes

- Created `mirasoth/soothe-plugins` with filtered git history + WIP weaver
  self-registration commit; dropped monorepo `[tool.uv.sources]` workspace pins
- Monorepo: `.gitmodules` entry; path is a gitlink
- Removed monorepo `.github/workflows/release.yml` `deploy-plugins` job
  (publish via plugins repo `release.yml` on GitHub Release)
- Updated `AGENTS.md` and release skill inventory

## Acceptance

- `git submodule status packages/soothe-plugins` shows a commit on
  `mirasoth/soothe-plugins`
- `uv sync` resolves workspace member from submodule path
- Core packages remain weaver-blind
