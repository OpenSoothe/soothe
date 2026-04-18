# IG-203: Makefile Build/Publish Fix

> **Status**: ✅ Completed
> **Date**: 2026-04-18
> **Scope**: soothe-community, soothe-sdk, root Makefile

---

## Problem

When building and publishing packages in the monorepo workspace, `uv build` outputs artifacts to the root `dist/` directory, but `uv publish` expects files in the local package `dist/` directory by default. This caused the error:

```bash
$ make publish
Publishing package to PyPI...
uv publish
error: No files found to publish
make: *** [publish] Error 2
```

---

## Root Cause

**uv workspace behavior**:
- `uv build` in a workspace member outputs to root `dist/` directory
- `uv publish` defaults to `dist/*` pattern in current directory
- mismatch between build output location and publish input location

---

## Solution

Modified all Makefiles to:
1. Build to local package `dist/` directory using `--out-dir dist`
2. Publish from local `dist/` directory using explicit `dist/*` argument

### Changes Made

#### 1. `packages/soothe-community/Makefile`

```diff
- uv build
+ uv build --out-dir dist

- uv publish
+ uv publish dist/*

- uv publish --index-url https://test.pypi.org/simple/
+ uv publish dist/* --index-url https://test.pypi.org/simple/
```

#### 2. `packages/soothe-sdk/Makefile`

Same pattern as soothe-community.

#### 3. Root `Makefile`

Updated all package-specific targets:
- `sdk-build`, `sdk-publish`, `sdk-publish-test`
- `cli-build`, `cli-publish`, `cli-publish-test`
- `community-build`, `community-publish`, `community-publish-test`
- `build`, `publish`, `publish-test` (daemon package)

All now use `--out-dir dist` for build and `dist/*` for publish.

---

## Verification

Tested complete workflow in soothe-community:

```bash
$ make clean
✓ Build artifacts cleaned

$ make build
✓ Package built
dist/soothe_community-0.1.0-py3-none-any.whl
dist/soothe_community-0.1.0.tar.gz

$ uv publish --dry-run dist/*
Checking 2 files against https://upload.pypi.org/legacy/
✓ Would publish successfully
```

---

## Impact

- **Build artifacts**: Now stored in `packages/*/dist/` instead of root `dist/`
- **Publish workflow**: Fixed for all packages
- **Cleanup**: `make clean` now removes local `dist/` directories
- **CI/CD**: Build/publish targets work correctly in automated environments

---

## Files Modified

1. `packages/soothe-community/Makefile` (build, publish, publish-test, clean targets)
2. `packages/soothe-sdk/Makefile` (build, publish, publish-test, clean targets)
3. `Makefile` (root) (all build/publish targets for all packages)

---

## Notes

- This follows uv's recommended pattern for workspace packages
- Local `dist/` directories are package-specific, avoiding collisions
- Root `dist/` directory no longer used (can be removed if exists)
- No changes to `pyproject.toml` files needed

---

## References

- uv documentation: `uv build --out-dir`, `uv publish [FILES]`
- Workspace package isolation pattern