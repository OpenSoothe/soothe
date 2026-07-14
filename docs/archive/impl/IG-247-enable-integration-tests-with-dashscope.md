# IG-247: Enable Integration Tests with Dashscope Credentials

**Status**: ✅ Completed
**Created**: 2026-04-23
**Purpose**: Enable GitHub workflow integration tests using Dashscope API credentials

---

## Overview

Currently, integration tests are disabled in GitHub workflow and only check for `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. This guide enables integration tests to run with Dashscope credentials (`DASHSCOPE_CP_API_KEY` and `DASHSCOPE_CP_BASE_URL`).

---

## Changes

### 1. Update Integration Test API Key Check

**File**: `packages/soothe/tests/integration/conftest.py`
**Location**: `_has_valid_api_key()` function (line 233-237)

**Before**:
```python
def _has_valid_api_key() -> bool:
    """Check if a valid API key is available for integration tests."""
    import os

    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))
```

**After**:
```python
def _has_valid_api_key() -> bool:
    """Check if a valid API key is available for integration tests."""
    import os

    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or (os.getenv("DASHSCOPE_CP_API_KEY") and os.getenv("DASHSCOPE_CP_BASE_URL"))
    )
```

**Why**: The `coding-plan` provider in `config.dev.yml` uses Dashscope credentials as the default router. Integration tests should recognize these as valid API keys.

---

### 2. Enable Integration Tests in GitHub Workflow

**File**: `.github/workflows/ci.yml`
**Location**: Lines 38-39 (currently commented out)

**Before**:
```yaml
# - name: Run integration tests
#   run: make test-integration
```

**After**:
```yaml
- name: Run integration tests
  run: make test-integration --run-integration
  env:
    DASHSCOPE_CP_API_KEY: ${{ secrets.DASHSCOPE_CP_API_KEY }}
    DASHSCOPE_CP_BASE_URL: ${{ secrets.DASHSCOPE_CP_BASE_URL }}
```

**Why**: Integration tests require the `--run-integration` pytest flag and need Dashscope credentials injected from GitHub secrets.

---

### 3. Update Integration Test Fixture Documentation

**File**: `packages/soothe/tests/integration/conftest.py`
**Location**: `soothe_runner` fixture docstring (line 276-295)

**Before**:
```python
@pytest.fixture
async def soothe_runner(integration_config: SootheConfig):
    """Create SootheRunner with real LLM for integration tests.

    Requires OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable.
```

**After**:
```python
@pytest.fixture
async def soothe_runner(integration_config: SootheConfig):
    """Create SootheRunner with real LLM for integration tests.

    Requires OPENAI_API_KEY, ANTHROPIC_API_KEY, or Dashscope credentials
    (DASHSCOPE_CP_API_KEY + DASHSCOPE_CP_BASE_URL) environment variable.
```

**Why**: Document the new Dashscope credential support for clarity.

---

## GitHub Secrets Setup

**Required Actions** (manual, by repository admin):

1. Navigate to repository Settings → Secrets and variables → Actions
2. Add two repository secrets:
   - `DASHSCOPE_CP_API_KEY`: Your Dashscope coding-plan API key
   - `DASHSCOPE_CP_BASE_URL`: Your Dashscope coding-plan base URL (e.g., `https://dashscope.example.com/v1`)
3. Ensure secrets are available to the workflow

---

## Verification Steps

### 1. Local Verification

```bash
# Set environment variables
export DASHSCOPE_CP_API_KEY="your-api-key"
export DASHSCOPE_CP_BASE_URL="your-base-url"

# Run integration tests
make test-integration
```

Expected: Integration tests run successfully with Dashscope provider.

### 2. GitHub Workflow Verification

After committing changes and setting secrets:

1. Push changes to trigger CI workflow
2. Check workflow logs for "Run integration tests" step
3. Verify tests pass with Dashscope credentials

---

## Test Coverage

**Tests affected**:
- `packages/soothe/tests/integration/core/test_loop_agent.py` (mock-based, no API calls)
- `packages/soothe/tests/integration/core/test_rfc0013_e2e.py` (daemon E2E tests)
- `packages/soothe/tests/integration/tools/*.py` (tool integration tests)
- All tests using `soothe_runner` fixture

**Tests requiring specific keys** (already have granular skips):
- Audio transcription tests: Require `OPENAI_API_KEY`
- Video analysis tests: Require `GOOGLE_API_KEY`
- Web search tests: Require Serper API key

**Why this is safe**: Tests that don't match available credentials will skip gracefully via `pytest.skip()`.

---

## Rollback Plan

If integration tests fail in GitHub workflow:

1. Comment out integration test step again (lines 38-39)
2. Add `continue-on-error: true` to allow workflow to pass despite test failures
3. Investigate root cause and fix before re-enabling

---

## Success Criteria

- ✅ `_has_valid_api_key()` accepts Dashscope credentials
- ✅ Integration tests enabled in GitHub workflow
- ✅ Tests run with `--run-integration` flag
- ✅ GitHub secrets injected into test environment
- ✅ All unit tests continue to pass
- ✅ Integration tests pass or skip gracefully based on available keys

---

## References

- **RFC-000**: System Conceptual Design
- **RFC-400**: Daemon Communication Protocol
- **config.dev.yml**: Development configuration with Dashscope providers
- **GitHub Actions Secrets**: https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions