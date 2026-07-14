# IG-203: Makefile Build and Publish Fix

**Status**: ✅ Completed
**Created**: 2026-04-18
**Scope**: Build and publish targets in package Makefiles

---

## Problem

PyPI publishing fails with TLS handshake timeout error:

```
error: Failed to publish `dist/soothe_community-0.1.0-py3-none-any.whl`
  Caused by: tls handshake eof
```

**Root Cause**: PyPI upload endpoint has slow connectivity, causing uv publish to timeout with default TLS settings.

---

## Solution

Add `--native-tls` flag to `uv publish` commands to use platform's native TLS certificate store.

```makefile
publish:
	@echo "Publishing package to PyPI..."
	uv publish dist/* --native-tls
	@echo "✓ Package published to PyPI"
```

**Why native-tls**: Uses macOS/Linux native certificate store instead of bundled certs, which resolves handshake issues.

---

## Implementation Plan

### Files to Update

1. `/Users/chenxm/Workspace/Soothe/Makefile` (monorepo root)
   - `publish`, `publish-test` (daemon package)
   - `sdk-publish`, `sdk-publish-test`
   - `cli-publish`, `cli-publish-test`
   - `community-publish`, `community-publish-test`

2. `/Users/chenxm/Workspace/Soothe/packages/soothe-community/Makefile`
   - `publish`, `publish-test`

3. `/Users/chenxm/Workspace/Soothe/packages/soothe-sdk/Makefile`
   - `publish`, `publish-test`

4. `/Users/chenxm/Workspace/Soothe/packages/soothe-cli/Makefile`
   - `publish`, `publish-test`

---

## Changes

Add `--native-tls` flag to all `uv publish` commands in publish targets.

---

## Verification

After changes, run:

```bash
make build
make publish
```

Should successfully publish without TLS errors.

---

## Verification Results

✅ Tested on soothe-community package:
```
Publishing package to PyPI...
uv publish dist/* --native-tls
Publishing 2 files to https://upload.pypi.org/legacy/
Uploading soothe_community-0.1.0-py3-none-any.whl (58.4KiB)
Uploading soothe_community-0.1.0.tar.gz (52.8KiB)
✓ Package published to PyPI
```

TLS handshake error resolved. Package successfully published.
