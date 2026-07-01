# IG-503: File Descriptor Leak and Network Resilience Fixes

> Status: **Implemented**
> Created: 2025-06-25
> Scope: Fix file descriptor exhaustion causing cascading failures; add connection error resilience to planner LLM calls

## Summary

This implementation addresses two critical issues identified in loop `2b67` log analysis:

1. **File Descriptor Exhaustion (errno 24)** - Fixed by adding pre-flight checks and explicit subprocess cleanup in `grep_search.py`
2. **LLM Connection Errors** - Fixed by adding retry with exponential backoff in `planner.py` and `llm_rate_limit.py`

All changes are backward compatible and require no configuration updates.

## Files Modified

- `packages/soothe/src/soothe/foundation/core/filesystem/grep_search.py` - FD limit handling
- `packages/soothe/src/soothe/foundation/sloop/planning/planner.py` - Network retry for planner LLM calls
- `packages/soothe/src/soothe/middleware/llm_rate_limit.py` - Connection error retry in middleware

## Problem Statement

### Issue 1: File Descriptor Exhaustion (`[Errno 24] Too many open files`)

**Symptoms from loop 2b67 log analysis:**
- `ag grep failed ([Errno 24] Too many open files)` - 5 occurrences
- `ThreadLogger flush failed` - OSError on conversation.jsonl
- `Graph invocation failed` - OSError on metadata.json
- Step failures cascading from resource exhaustion

**Root Cause Analysis:**

1. **`ag` subprocess behavior** (`grep_search.py:261-294`):
   - `ag` (The Silver Searcher) opens many files concurrently when searching large directories
   - When system ulimit (`ulimit -n`, typically 256 on macOS) is exceeded, `ag` fails with OSError 24
   - The subprocess failure doesn't properly cascade - fallback to Python walk works but `ag` process may leave FDs in bad state

2. **Concurrent grep operations**:
   - Multiple subagent steps running parallel grep operations
   - Each spawns `ag` subprocess which attempts to open hundreds of files
   - Combined load exceeds system FD limit

3. **Cascading failures**:
   - ThreadLogger, checkpoint persistence, and graph invocation all fail due to system-wide FD exhaustion

### Issue 2: LLM Connection Errors Without Proper Retry

**Symptoms from loop 2b67 log analysis:**
- `StatusAssessment failed: structured model invoke failed: Connection error` - 4 occurrences
- `PlanGeneration failed: structured model invoke failed: Connection error` - 4 occurrences
- Planner falls back to default plan after only 2 retries

**Root Cause Analysis:**

1. **Current retry handling** (`planner.py:968-977`):
   - Generic Exception catch with simple retry loop (max_retries=2)
   - No exponential backoff for transient network failures
   - Connection errors lumped with other exceptions

2. **Missing middleware coverage**:
   - `LLMRateLimitMiddleware` handles timeout and 429 but not generic connection errors
   - `NetworkToolErrorsMiddleware` only covers tool calls, not planner LLM calls
   - Planner's structured output calls (`_assess_status_with_response`, `_generate_plan`) bypass middleware

---

## Implementation Plan

### Phase 1: File Descriptor Leak Fix (grep_search.py)

**File:** `packages/soothe/src/soothe/foundation/core/filesystem/grep_search.py`

#### Change 1.1: Add FD limit detection and proactive fallback

```python
# New constant near line 18
_MAX_FD_SAFE_FILE_COUNT = 200  # Safe threshold before hitting typical ulimit (256)
```

#### Change 1.2: Add pre-flight FD check in `_run_ag_subprocess`

Before spawning `ag`, check if the search directory has too many files. If so, skip `ag` and use Python fallback proactively.

```python
def _should_skip_ag_due_to_fd_limit(search_path: Path) -> bool:
    """Check if directory size might exceed FD limit."""
    if not search_path.is_dir():
        return False
    try:
        # Quick estimate: count files in top 2 levels
        count = 0
        for item in search_path.iterdir():
            if item.is_file():
                count += 1
            elif item.is_dir():
                try:
                    for sub in item.iterdir():
                        if sub.is_file():
                            count += 1
                except OSError:
                    pass
            if count > _MAX_FD_SAFE_FILE_COUNT:
                return True
        return False
    except OSError:
        return True  # Can't read dir, skip ag
```

#### Change 1.3: Improve subprocess cleanup in `_run_ag_subprocess`

Use `subprocess.Popen` with explicit resource management:

```python
def _run_ag_subprocess(
    cmd: list[str], *, timeout_s: float
) -> subprocess.CompletedProcess[str] | None:
    """Run ``ag`` with explicit FD management."""
    stdout_path: str | None = None
    proc: subprocess.Popen | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".agout") as tmp:
            stdout_path = tmp.name

        proc = subprocess.Popen(
            cmd,
            stdout=open(stdout_path, "w", encoding="utf-8"),
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout_fh = proc.stdout  # Keep reference for explicit close

        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)  # Grace period after kill
            logger.warning("ag grep timed out after %ss; falling back to Python walk", timeout_s)
            return None

        # Read output
        with open(stdout_path, encoding="utf-8") as f:
            stdout = f.read()

        return subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=proc.stderr.read() if proc.stderr else "",
        )
    except OSError as exc:
        if exc.errno == 24:  # EMFILE - too many open files
            logger.warning(
                "ag grep hit FD limit (errno 24); falling back to Python walk. "
                "Consider increasing ulimit -n."
            )
        else:
            logger.warning("ag grep failed (%s); falling back to Python walk", exc)
        return None
    finally:
        # Explicit cleanup order: process -> stdout_fh -> temp file
        if proc is not None:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        if stdout_path is not None:
            try:
                os.unlink(stdout_path)
            except OSError:
                pass
```

#### Change 1.4: Add FD exhaustion recovery in `grep_with_ag`

When `ag` fails with errno 24, emit actionable guidance:

```python
# In grep_with_ag, after getting None from _run_ag_subprocess
completed = _run_ag_subprocess(cmd, timeout_s=timeout_s)
if completed is None:
    # Log actionable guidance on FD exhaustion
    if hasattr(sys.exc_info()[1], 'errno') and sys.exc_info()[1].errno == 24:
        logger.warning(
            "System file descriptor limit reached. Increase with: ulimit -n 1024"
        )
    return None
```

---

### Phase 2: Network Resilience for Planner LLM Calls

**File:** `packages/soothe/src/soothe/foundation/sloop/planning/planner.py`

#### Change 2.1: Add connection error detection helper

```python
# Near line 30 (imports section)
import httpx

def _is_transient_network_error(exc: Exception) -> bool:
    """Detect transient network errors that warrant retry with backoff."""
    # Connection errors
    exc_type_name = type(exc).__name__
    if exc_type_name in ("ConnectionError", "ConnectError", "NetworkError"):
        return True

    # httpx specific
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.ReadTimeout):
        return True
    if isinstance(exc, httpx.WriteTimeout):
        return True

    # Check for connection-related keywords
    error_str = str(exc).lower()
    transient_keywords = [
        "connection error",
        "connection refused",
        "connection reset",
        "network unreachable",
        "timeout",
        "timed out",
        "socket error",
        "ssl error",
        "tls error",
        "eof occurred in violation of protocol",
    ]
    return any(kw in error_str for kw in transient_keywords)
```

#### Change 2.2: Add exponential backoff helper

```python
def _calculate_backoff_delay(attempt: int, base: float = 1.0, max_delay: float = 30.0) -> float:
    """Calculate exponential backoff: base * 2^attempt, capped at max."""
    delay = base * (2 ** attempt)
    return min(delay, max_delay)
```

#### Change 2.3: Enhanced retry in `_assess_status_with_response`

Replace the generic Exception handler with connection-error-aware retry:

```python
# Around line 702-742
except asyncio.CancelledError:
    raise
except Exception as e:
    # Check if this is a transient network error
    if _is_transient_network_error(e):
        # Retry with exponential backoff (up to 3 times)
        for attempt in range(3):
            backoff = _calculate_backoff_delay(attempt, base=2.0, max_delay=15.0)
            logger.warning(
                "[LLMPlanner] StatusAssessment network error (attempt %d/3): %s - retrying in %.1fs",
                attempt + 1,
                str(e)[:100],
                backoff,
            )
            await asyncio.sleep(backoff)
            try:
                assessment = await model.ainvoke(messages, config=lf_cfg)
                # ... success handling
                return assessment, assessment
            except Exception as retry_exc:
                if not _is_transient_network_error(retry_exc):
                    break  # Non-transient error, stop retrying
                e = retry_exc
                continue

        # All retries exhausted, fall through to fallback
        logger.error("[LLMPlanner] StatusAssessment network error after 3 retries")

    # Non-network error or retries exhausted
    logger.warning("[LLMPlanner] StatusAssessment failed: %s", str(e)[:200])
    # ... existing fallback logic
```

#### Change 2.4: Enhanced retry in `_generate_plan`

Same pattern for plan generation:

```python
# Around line 968-977
except Exception as e:
    # Transient network error retry
    if _is_transient_network_error(e):
        for attempt in range(3):
            backoff = _calculate_backoff_delay(attempt, base=2.0, max_delay=30.0)
            logger.warning(
                "[LLMPlanner] PlanGeneration network error (attempt %d/3): %s - retrying in %.1fs",
                attempt + 1,
                str(e)[:100],
                backoff,
            )
            await asyncio.sleep(backoff)
            try:
                plan_result = await _invoke_plan_structured_output(...)
                if plan_result is not None:
                    return plan_result, plan_result
            except Exception as retry_exc:
                if not _is_transient_network_error(retry_exc):
                    break
                e = retry_exc
                continue

        logger.error("[LLMPlanner] PlanGeneration network error after 3 retries")
        last_error = e
        # Fall through to existing fallback

    # Existing generic handling
    last_error = e
    if attempt < max_retries:
        logger.debug("[LLMPlanner] Retrying after error (attempt %d/%d)", ...)
        continue
```

---

### Phase 3: LLMRateLimitMiddleware Extension (Optional Enhancement)

**File:** `packages/soothe/src/soothe/middleware/llm_rate_limit.py`

#### Change 3.1: Add connection error retry to middleware

Extend `_is_api_rate_limit_error` pattern to connection errors:

```python
def _is_transient_connection_error(exc: Exception) -> bool:
    """Check for transient connection errors that warrant retry."""
    exc_type_name = type(exc).__name__
    transient_types = {
        "ConnectionError", "ConnectError", "NetworkError",
        "ReadTimeout", "WriteTimeout",
    }
    if exc_type_name in transient_types:
        return True

    # httpx exceptions
    if "httpx" in str(type(exc).__module__):
        if exc_type_name in ("ConnectError", "ReadTimeout", "WriteTimeout", "ConnectTimeout"):
            return True

    return False
```

#### Change 3.2: Add connection error handling to `awrap_model_call`

```python
# In the retry loop around line 691-790
connection_attempts = 0
max_connection_attempts = 3

# Add new exception handler after TimeoutError and rate limit handlers
except Exception as exc:
    if _is_transient_connection_error(exc):
        connection_attempts += 1
        if connection_attempts < max_connection_attempts:
            backoff = 2.0 * connection_attempts
            logger.warning(
                "LLM connection error (attempt %d/%d) - retrying with backoff=%.1fs (thread_id=%s)",
                connection_attempts,
                max_connection_attempts,
                backoff,
                thread_id,
            )
            await asyncio.sleep(backoff)
            continue
        else:
            logger.error(
                "LLM connection error after %d retries (thread_id=%s)",
                max_connection_attempts,
                thread_id,
            )
            raise
    elif _is_api_rate_limit_error(exc):
        # ... existing 429 handling
    else:
        # Non-transient error: propagate immediately
        raise
```

---

## Testing Plan

### Test 1: File Descriptor Handling

```python
# tests/core/filesystem/test_grep_search_fd_handling.py

def test_ag_skipped_on_large_directory():
    """When directory exceeds FD-safe threshold, skip ag and use Python fallback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create 300 files
        for i in range(300):
            Path(tmpdir, f"file_{i}.txt").write_text("content")

        result = grep_with_ag(
            workspace=Path(tmpdir),
            search_path=Path(tmpdir),
            pattern="content",
            glob=None,
            output_mode="files_with_matches",
        )
        # Should fallback to Python, not fail
        assert result is not None

def test_ag_handles_errno_24_gracefully():
    """When ag fails with errno 24, fallback gracefully without cascade."""
    # Mock subprocess to raise OSError(24)
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.side_effect = OSError(24, "Too many open files")
        result = _run_ag_subprocess(["ag", "test"], timeout_s=30)
        assert result is None  # Graceful fallback
```

### Test 2: Network Error Retry

```python
# tests/unit/core/loop/planning/test_planner_network_retry.py

@pytest.mark.asyncio
async def test_assess_status_retries_on_connection_error():
    """StatusAssessment retries with backoff on transient connection errors."""
    planner = LLMPlanner(...)

    # Mock model to fail twice then succeed
    call_count = 0
    async def mock_invoke(*args, **kwargs):
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Network unreachable")
        return StatusAssessment(status="continue", goal_progress="medium")

    planner._model.ainvoke = mock_invoke

    result = await planner._assess_status_with_response(...)
    assert result.status == "continue"
    assert call_count == 3  # 2 failures + 1 success

@pytest.mark.asyncio
async def test_generate_plan_retries_on_connection_error():
    """PlanGeneration retries with exponential backoff."""
    # Similar test pattern
```

---

## Configuration Impact

No configuration changes required. Both fixes are code-level resilience improvements.

---

## Migration Notes

- Backward compatible - no API changes
- Existing retry configurations in `LLMRateLimitMiddleware` remain unchanged
- Planner retry behavior enhanced but fallback behavior unchanged

---

## Acceptance Criteria

1. **FD Leak**: `ag` subprocess failures no longer cascade to ThreadLogger and checkpoint persistence
2. **FD Leak**: System with default ulimit (256) can handle parallel grep operations without exhaustion
3. **Network**: Connection errors retry up to 3 times with exponential backoff before fallback
4. **Network**: Log analysis shows retry attempts and backoff delays for transient errors
5. **Tests**: All new tests pass; existing tests unchanged

---

## References

- Log analysis: loop 2b67 in `~/.soothe/logs/soothe.log`
- Related: IG-258 (thread-local rate limiting), IG-295 (timeout retry), IG-499 (429 retry)