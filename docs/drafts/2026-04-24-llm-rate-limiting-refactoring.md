# LLM-Level Rate Limiting Refactoring

**Date**: 2026-04-24
**Status**: Completed
**Impact**: Fixes thread hanging issues, improves concurrent query performance

## Problem

Thread-level rate limiting caused queries to hang for 30+ seconds when multiple queries ran concurrently:

1. **Thread `majreh32nrad`** (browser subagent) started at 17:42:25
2. Acquired semaphore permit and held it for **141 seconds** (entire thread lifecycle)
3. **Thread `ihvgh9y8l5pi`** ("explore count all readme") tried to start at 17:42:25
4. **Blocked waiting for permit** - entire thread execution halted
5. Only started execution at **17:42:59** (34 second delay)

### Root Cause Analysis

**Thread-level blocking** (old approach):
```python
# ThreadExecutor - blocks entire thread
async def execute_thread(self, thread_id, user_input, **kwargs):
    async with self._rate_limiter.acquire():  # ← Semaphore with 2 permits
        async for chunk in self._runner.astream(...):
            yield chunk
```

- Semaphore had only **2 permits** (120 RPM ÷ 60 = 2)
- Thread held permit for **entire execution** including:
  - Classification
  - Multiple LLM calls
  - Tool executions
  - Subagent spawning
  - Final response generation
- Only **2 threads** could execute at any time
- Other threads **hung waiting** for permits

---

## Solution

Moved rate limiting to **LLM API call level** using custom middleware:

### Implementation

**LLMRateLimitMiddleware** (new approach):
```python
# Throttles individual LLM calls, not entire threads
class LLMRateLimitMiddleware(AgentMiddleware):
    def awrap_model_call(self, request, handler):
        async with self._semaphore:  # ← Max concurrent requests
            await self._enforce_rpm_limit()  # ← Sliding window RPM
            response = await handler(request)  # ← Actual LLM call
            await self._record_request_time()
            return response
```

**ThreadExecutor** (no blocking):
```python
async def execute_thread(self, thread_id, user_input, **kwargs):
    logger.info("Executing query in thread %s", thread_id)
    # ✅ No thread-level rate limiting
    # ✅ Threads start immediately
    async for chunk in self._runner.astream(...):
        yield chunk
```

---

## Benefits

### 1. **Thread Startup**: Immediate vs 30-second delay
- Old: Threads blocked waiting for permits (up to minutes)
- New: Threads start immediately, share LLM permits dynamically

### 2. **Concurrency**: 100 threads vs 2 threads
- Old: Only 2 threads could execute at any time
- New: 100 threads can run concurrently (max_concurrent_threads=100)
  - Share 10 LLM API permits dynamically (configurable)

### 3. **Permit Hold Duration**: Seconds vs Minutes
- Old: Thread held permit for entire lifecycle (minutes)
- New: Permit held only during LLM call (seconds), then released

### 4. **Throughput**: High vs Very Low
- Old: Permits monopolized, low actual throughput
- New: Permits reused frequently, high throughput

### 5. **Fairness**: Round-robin vs First-thread monopolizes
- Old: First threads monopolize permits
- New: Round-robin API call scheduling

### 6. **User Experience**: Smooth vs Hanging
- Old: Queries visibly hang for 30+ seconds
- New: Smooth concurrent execution

---

## Configuration

### Default Settings

```yaml
# In config/config.yml or config/config.dev.yml
performance:
  llm_rpm_limit: 120            # Requests per minute (sliding window)
  llm_concurrent_limit: 10      # Max concurrent LLM calls
```

### Middleware Stack Order

```python
build_soothe_middleware_stack():
    # 1. Policy enforcement
    # 2. System prompt optimization  
    # 3. LLM rate limiting ← NEW (throttles API calls, not threads)
    # 4. LLM tracing
    # 5. Execution hints
    # 6. Workspace context
    # 7. Per-turn model override
```

---

## Technical Details

### Sliding Window Algorithm

```python
# Track request times in 60-second sliding window
self._request_times: list[float] = []

async def _enforce_rpm_limit(self):
    now = time.time()
    window_start = now - 60.0
    
    # Remove requests older than 1 minute
    self._request_times = [t for t in self._request_times if t > window_start]
    
    # Check RPM limit
    if len(self._request_times) >= self._rpm_limit:
        # Wait until oldest request exits window
        wait_seconds = oldest_time + 60.0 - now
        await asyncio.sleep(wait_seconds)
```

### Semaphore for Concurrent Requests

```python
# Limit concurrent LLM calls at any instant
self._semaphore = asyncio.Semaphore(max_concurrent_requests)

async with self._semaphore:  # Max 10 concurrent calls
    response = await handler(request)  # Make LLM call
```

---

## Files Changed

### Created
- `packages/soothe/src/soothe/middleware/llm_rate_limit.py` - New middleware

### Modified  
- `packages/soothe/src/soothe/core/thread/executor.py` - Removed thread-level blocking
- `packages/soothe/src/soothe/middleware/_builder.py` - Added LLMRateLimitMiddleware
- `packages/soothe/src/soothe/middleware/__init__.py` - Exported new middleware
- `packages/soothe/src/soothe/core/thread/__init__.py` - Removed APIRateLimiter export

### Deleted
- `packages/soothe/src/soothe/core/thread/rate_limiter.py` - Obsolete thread-level limiter

---

## Testing

All verification checks passed:
- ✅ Code formatting check
- ✅ Linting check (zero errors)
- ✅ Unit tests (1275 passed, 2 skipped, 1 xfailed)
- ✅ Import boundary checks
- ✅ Workspace integrity

---

## Future Improvements

1. **Token-aware rate limiting**: Track token usage, not just request count
2. **Per-model rate limits**: Different limits for different models
3. **Dynamic adjustment**: Adjust limits based on API responses
4. **Statistics API**: Real-time rate limiting stats for monitoring

---

## References

- Log analysis: `~/.soothe/logs/soothe-daemon.log` (2026-04-24 17:42:25-17:42:59)
- Related RFC: Thread management and concurrency
- Middleware documentation: `packages/soothe/src/soothe/middleware/__init__.py`