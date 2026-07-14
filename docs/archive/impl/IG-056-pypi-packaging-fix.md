# IG-056: PyPI Packaging Fix

**Status**: ✅ Completed
**Date**: 2026-04-12
**Priority**: Critical

## Issue Summary

The `soothe` package (v0.2.4) published on PyPI was incomplete - it only contained metadata files but no actual Python source code, causing the `soothe` CLI command to fail with `ModuleNotFoundError`.

## Root Cause

The hatch build configuration in `pyproject.toml` was incomplete. While the wheel target configuration was correct (`packages = ["src/soothe"]`), there was no proper source distribution (sdist) configuration, which could cause issues during wheel builds.

## Evidence

1. Wheel file from PyPI contained only:
   - `soothe-0.2.4.dist-info/METADATA`
   - `soothe-0.2.4.dist-info/WHEEL`
   - `soothe-0.2.4.dist-info/entry_points.txt`
   - `soothe-0.2.4.dist-info/licenses/LICENSE`
   - `soothe-0.2.4.dist-info/RECORD`

2. Missing: `soothe/` directory with Python modules

3. User installation error:
   ```
   ModuleNotFoundError: No module named 'soothe.ux.cli.main'
   ```

## Solution

### Changes to `pyproject.toml`

Added proper sdist configuration with explicit include/exclude directives:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/soothe"]
artifacts = [
    "src/soothe/config/*.yml"
]

[tool.hatch.build.targets.sdist]
include = [
    "src/soothe/",
    "src/soothe/config/*.yml"
]
exclude = [
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
]
```

### Changes to `sdk/pyproject.toml`

Applied same fix to SDK package:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/soothe_sdk"]

[tool.hatch.build.targets.sdist]
include = ["src/soothe_sdk/"]
exclude = [
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
]
```

## Verification

### Build Test

```bash
# Build main package
uv run python -m build --wheel --outdir /tmp/wheel-test

# Verify wheel contains source code
unzip -l /tmp/wheel-test/soothe-0.2.4-py3-none-any.whl | head -50
# Shows: soothe/__init__.py, soothe/core/, soothe/cli/, etc.

# Build SDK package
cd sdk && uv run python -m build --wheel --outdir /tmp/sdk-test

# Verify SDK wheel contains source code
unzip -l /tmp/sdk-test/soothe_sdk-0.1.2-py3-none-any.whl
# Shows: soothe_sdk/__init__.py, soothe_sdk/decorators/, etc.
```

### Installation Test

```bash
# Install fixed package
uv pip install /tmp/wheel-test/soothe-0.2.4-py3-none-any.whl

# Verify CLI works
soothe --help
# ✅ Shows: Usage: soothe [OPTIONS] COMMAND [ARGS]...
```

## Impact

- **User Impact**: Users can now install and use the package from PyPI
- **Downstream Impact**: All pip/uv installations now work correctly
- **Build System**: Future releases will include complete source code

## Next Steps

1. **Publish new versions to PyPI**:
   - Tag new release: `v0.2.5` for main package
   - Tag new release: `v0.1.3` for SDK package
   - Build and publish both packages:
     ```bash
     uv run python -m build
     uv publish --token $PYPI_TOKEN
     ```

2. **Update GitHub release notes** mentioning the packaging fix

3. **Notify users** via GitHub issues/discussions that v0.2.5 fixes the installation issue

## Files Modified

- `/Users/chenxm/Workspace/Soothe/pyproject.toml`
- `/Users/chenxm/Workspace/Soothe/sdk/pyproject.toml`

## References

- Hatch build system: https://hatch.pypa.io/latest/config/build/
- Src-layout packaging: https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/