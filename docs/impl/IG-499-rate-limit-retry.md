# IG-499: HTTP 429 Rate Limit Retry Enhancement

## Problem

HTTP 429 ("Too Many Requests") errors from LLM providers (OpenAI, Anthropic) are detected but **not retried** at the middleware layer. Current behavior:

1. `LLMRateLimitMiddleware` retries `TimeoutError` only (IG-295)
2. 429 API errors propagate to `execute_steps.py`
3. `consecutive_rate_limit_errors` counter increments
4. After threshold (default 3), circuit breaker terminates the loop

This wastes retries and causes premature loop termination instead of graceful backoff.

## Solution

Add **HTTP 429 retry with exponential backoff** in `LLMRateLimitMiddleware`:

### Phase 1: Config Extension

Extend `LLMRateLimitConfig` in `config/models.py`:

```python
class LLMRateLimitConfig(BaseModel):
    # Existing fields...
    retry_on_timeout: bool = True
    max_timeout_retries: int = Field(default=2, ge=0, le=5)
    timeout_retry_multiplier: float = Field(default=1.2, ge=1.0, le=5.0)

    # NEW: 429 retry configuration
    retry_on_rate_limit: bool = Field(
        default=True,
        description="Retry LLM calls on HTTP 429 rate limit errors",
    )
    max_rate_limit_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retry attempts after 429 error",
    )
    rate_limit_backoff_base: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Exponential backoff base (seconds)",
    )
    rate_limit_backoff_max: float = Field(
        default=60.0,
        ge=10.0,
        le=300.0,
        description="Maximum backoff wait (seconds)",
    )
    respect_retry_after_header: bool = Field(
        default=True,
        description="Use retry-after header from API when present",
    )
```

### Phase 2: Middleware Enhancement

Enhance `LLMRateLimitMiddleware.awrap_model_call()` in `middleware/llm_rate_limit.py`:

1. **Catch 429 errors**: Check for OpenAI/Anthropic `RateLimitError` (subclass of `APIStatusError`)
2. **Extract retry-after**: Parse `retry-after` header from response when available
3. **Calculate backoff**: `min(backoff_base * 2^attempt, backoff_max)` or use `retry-after`
4. **Retry with wait**: Sleep before retry, then re-attempt the handler call

```python
# Error detection helper
def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if exception is a 429 rate limit error from OpenAI/Anthropic."""
    # Check class hierarchy (OpenAI/Anthropic RateLimitError)
    exc_type = type(exc).__name__
    if exc_type == "RateLimitError":
        return True
    # Check status_code on response attribute
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        return status == 429
    # Fallback: string matching
    error_str = str(exc)
    return "429" in error_str or "rate limit" in error_str.lower()

# Backoff calculation
def _extract_retry_after(exc: Exception) -> float | None:
    """Extract retry-after header value from API error response."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    retry_after = headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None
```

### Phase 3: Retry Loop Integration

Modify `awrap_model_call()` to handle both timeout and rate limit retries:

```python
async def awrap_model_call(self, request, handler) -> ModelResponse:
    thread_id = self._thread_id_from_request(request)

    # Separate retry counters for different error types
    timeout_attempts = 0
    rate_limit_attempts = 0
    max_timeout = self._max_timeout_retries if self._retry_on_timeout else 0
    max_rate_limit = self._max_rate_limit_retries if self._retry_on_rate_limit else 0

    budget = await self._get_thread_budget(thread_id)
    async with budget.semaphore:
        await budget.wait_for_rpm_slot()

        while True:
            eff_timeout = self._calculate_retry_timeout(
                base_timeout=self._call_timeout,
                attempt=timeout_attempts,
            )

            try:
                response = await asyncio.wait_for(handler(request), timeout=eff_timeout)
                budget.record_request()
                return response

            except TimeoutError:
                if timeout_attempts < max_timeout:
                    timeout_attempts += 1
                    backoff = 1.0 * timeout_attempts
                    logger.debug("Timeout retry %d/%d, backoff=%.1fs", timeout_attempts, max_timeout, backoff)
                    await asyncio.sleep(backoff)
                    continue
                else:
                    raise EnhancedTimeoutError(...)

            except Exception as exc:
                if _is_rate_limit_error(exc) and rate_limit_attempts < max_rate_limit:
                    rate_limit_attempts += 1
                    # Prefer retry-after header if available
                    retry_after = _extract_retry_after(exc) if self._respect_retry_after_header else None
                    if retry_after is not None:
                        backoff = min(retry_after, self._rate_limit_backoff_max)
                    else:
                        backoff = min(
                            self._rate_limit_backoff_base * (2 ** (rate_limit_attempts - 1)),
                            self._rate_limit_backoff_max,
                        )
                    logger.warning(
                        "Rate limit (429) retry %d/%d, backoff=%.1fs (thread_id=%s)",
                        rate_limit_attempts,
                        max_rate_limit,
                        backoff,
                        thread_id,
                    )
                    await asyncio.sleep(backoff)
                    continue
                else:
                    raise
```

### Phase 4: Config Sync

Update both config files:
- `config/config.template.yml`
- `config/config.dev.yml`

Add under `agent.loop.llm_rate_limit`:

```yaml
llm_rate_limit:
  enabled: true
  rpm_limit: 120
  concurrent_limit: 10
  call_timeout_seconds: 120
  call_timeout_max_seconds: 300
  retry_on_timeout: true
  max_timeout_retries: 2
  timeout_retry_multiplier: 1.2
  # NEW: 429 retry settings
  retry_on_rate_limit: true
  max_rate_limit_retries: 3
  rate_limit_backoff_base: 2.0
  rate_limit_backoff_max: 60.0
  respect_retry_after_header: true
```

## Error Classes Affected

| Provider | Error Class | Parent | status_code access |
|----------|-------------|--------|-------------------|
| OpenAI | `openai.RateLimitError` | `APIStatusError` | `exc.response.status_code` |
| Anthropic | `anthropic.RateLimitError` | `APIStatusError` | `exc.response.status_code` |

## Testing

1. Mock 429 error in middleware tests
2. Verify retry count and backoff timing
3. Test `retry-after` header parsing
4. Verify loop doesn't terminate on transient 429s

## Out of Scope

- Circuit breaker threshold adjustment (separate config)
- Cross-thread rate limit coordination (thread-local budgets sufficient)