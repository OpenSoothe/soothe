# Design Draft: Dynamic LLM Rate Limit Adjustment

**Date**: 2026-06-19
**Author**: Design session via brainstorming
**Scope**: Enable LLM rate limiting by default with runtime RPM adjustment based on provider feedback

---

## Problem Statement

The system experiences LLM timeouts (120s) and potential rate limiting from Chinese providers (Dashscope, Zhipu). The current `LLMRateLimitMiddleware`:

1. Is **disabled by default** (`enabled: false`)
2. Uses **conservative defaults** suited for OpenAI (rpm=120, concurrent=10)
3. **Cannot dynamically adjust** when provider signals rate limits
4. Only uses retry-after header for backoff, not for permanent RPM reduction

Chinese providers typically have lower rate limits and may communicate limits differently than OpenAI/Anthropic.

---

## Goals

1. **Enable rate limiting by default** with moderate settings appropriate for Chinese providers
2. **Extract rate limit info** from provider 429 errors (retry-after, RPM hints, provider identification)
3. **Runtime RPM adjustment** - dynamically reduce global RPM limit when rate limits detected
4. **Log all adjustments** - visibility into when/why limits change
5. **Proactive throttling** - reduce RPM after consecutive timeouts (provider overload indicator)

---

## Non-Goals

- Config file modification at runtime (user explicitly excluded)
- Provider-specific static profiles in config
- Complex singleton observer architecture
- TPM (tokens-per-minute) limiting - focus on RPM only

---

## Architecture

### Component Changes

| Component | Change |
|-----------|--------|
| `LLMRateLimitConfig` | Enable by default, moderate values |
| `config/config.template.yml` | Update defaults with rationale |
| `config/develop/config.yml` | Sync with template |
| `llm_rate_limit.py` | New extraction function, adjustment method, integration |

### Data Flow

```
LLM Call → 429 Error → _extract_rate_limit_info(exc)
                              ↓
                     {retry_after, rpm_hint, provider}
                              ↓
              adjust_rpm_limit(rpm_hint, reason) ← if hint available
                              ↓
                     Log + redistribute budgets
                              ↓
                     Continue retry with backoff
```

---

## Implementation Details

### 1. Configuration Changes

**`LLMRateLimitConfig` defaults (models.py):**

```python
enabled: bool = True  # Changed from False
rpm_limit: int = 60   # Changed from 120
concurrent_limit: int = 8  # Changed from 10
call_timeout_seconds: int = 150  # Changed from 120
```

**Rationale:**
- `rpm_limit: 60` - Suitable for Chinese providers (Dashscope free tier ~30 RPM, paid ~60-100)
- `concurrent_limit: 8` - Parallelism without overwhelming provider
- `timeout: 150s` - Extra margin for slower Chinese provider response times

**Config template update:**

```yaml
llm_rate_limit:
  enabled: true  # Enable by default for Chinese providers
  rpm_limit: 60  # Moderate default for Dashscope/Zhipu
  concurrent_limit: 8
  call_timeout_seconds: 150  # Extra margin for slower responses
  call_timeout_max_seconds: 300
  retry_on_timeout: true
  max_timeout_retries: 2
  timeout_retry_multiplier: 1.2
  retry_on_rate_limit: true
  max_rate_limit_retries: 3
  rate_limit_backoff_base: 2.0
  rate_limit_backoff_max: 60.0
  respect_retry_after_header: true
```

### 2. Rate Limit Info Extraction

**New function `_extract_rate_limit_info()`:**

Extracts from 429 error response:
- `retry_after_seconds` - When to retry (header or body)
- `rpm_limit_hint` - Provider's actual RPM limit (if communicated)
- `provider_name` - Detected provider (dashscope/zhipu/etc)

```python
def _extract_rate_limit_info(exc: Exception) -> dict[str, Any]:
    """Extract rate limit info from provider error response.

    Dashscope/Zhipu use OpenAI-compatible format:
    - HTTP 429 status
    - JSON body: {"error": {"code": "Throttling", "message": "..."}}
    - May include retry_after or wait_seconds in body

    Returns:
        dict with retry_after_seconds, rpm_limit_hint, provider_name
    """
    result = {"retry_after_seconds": None, "rpm_limit_hint": None, "provider_name": None}

    response = getattr(exc, "response", None)
    if response is None:
        return result

    # 1. Standard retry-after header
    headers = getattr(response, "headers", {})
    if headers:
        retry_after = headers.get("retry-after")
        if retry_after:
            result["retry_after_seconds"] = float(retry_after)

    # 2. Response body parsing
    try:
        body = response.json()
        error_obj = body.get("error", {})

        # Dashscope/Zhipu may include retry info in body
        if "retry_after" in error_obj:
            result["retry_after_seconds"] = float(error_obj["retry_after"])
        elif "wait_seconds" in error_obj:
            result["retry_after_seconds"] = float(error_obj["wait_seconds"])

        # Provider may communicate their actual limit
        if "rate_limit" in error_obj:
            limit_obj = error_obj.get("rate_limit", {})
            result["rpm_limit_hint"] = limit_obj.get("limit")

        # Detect provider from error code/message
        message = error_obj.get("message", "") or str(body)
        if "dashscope" in message.lower():
            result["provider_name"] = "dashscope"
        elif "zhipu" in message.lower() or "glm" in message.lower():
            result["provider_name"] = "zhipu"

    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    return result
```

### 3. Runtime RPM Adjustment

**New method `adjust_rpm_limit()` in `LLMRateLimitMiddleware`:**

```python
def adjust_rpm_limit(self, new_limit: int, reason: str) -> None:
    """Dynamically adjust global RPM limit based on provider feedback.

    Logs change, validates bounds, redistributes across thread budgets.

    Args:
        new_limit: New RPM limit (validated: 5-10000).
        reason: Reason string for logging.
    """
    # Validate bounds
    new_limit = max(5, min(new_limit, 10000))

    old_limit = self._rpm_limit_global
    if new_limit == old_limit:
        return  # No change needed

    self._rpm_limit_global = new_limit

    # Log the adjustment
    logger.warning(
        "RPM limit adjusted: %d → %d (reason: %s) active_threads=%d",
        old_limit,
        new_limit,
        reason,
        len(self._thread_budgets) if self._thread_local_enabled else 1,
    )

    # Redistribute to thread budgets (if thread-local mode)
    if self._thread_local_enabled:
        asyncio.create_task(self._redistribute_budgets())
```

### 4. Integration with Retry Flow

**429 error handling (in `awrap_model_call`):**

```python
except Exception as exc:
    if _is_api_rate_limit_error(exc):
        # Extract full rate limit info
        rate_limit_info = _extract_rate_limit_info(exc)

        # Log detection
        logger.warning(
            "Rate limit detected: retry_after=%ss rpm_hint=%s provider=%s",
            rate_limit_info["retry_after_seconds"] or "none",
            rate_limit_info["rpm_limit_hint"] or "none",
            rate_limit_info["provider_name"] or "unknown",
        )

        # Adjust RPM if provider gave hint
        if rate_limit_info["rpm_limit_hint"] is not None:
            self.adjust_rpm_limit(
                rate_limit_info["rpm_limit_hint"],
                reason=f"429 from {rate_limit_info['provider_name'] or 'provider'}"
            )

        # Existing retry logic continues...
        if rate_limit_attempts < max_rate_limit_attempts - 1:
            rate_limit_attempts += 1
            backoff = self._calculate_rate_limit_backoff(
                attempt=rate_limit_attempts - 1,
                exc=exc,
            )
            await asyncio.sleep(backoff)
            continue
        else:
            raise
```

**Proactive throttling after consecutive timeouts:**

Track per-thread consecutive timeout count. After 2+ consecutive timeouts:

```python
# In TimeoutError handling block
except TimeoutError:
    timeout_attempts += 1

    # Proactive throttling after 2+ consecutive timeouts
    if timeout_attempts >= 2:
        proactive_limit = int(self._rpm_limit_global * 0.8)  # Reduce by 20%
        self.adjust_rpm_limit(
            proactive_limit,
            reason=f"consecutive timeouts ({timeout_attempts}) suggesting provider overload"
        )

    # Existing retry logic...
```

### 5. Logging Specification

| Event | Level | Format |
|-------|-------|--------|
| RPM adjusted | WARNING | `RPM limit adjusted: {old} → {new} (reason: {reason}) active_threads={n}` |
| Rate limit detected | WARNING | `Rate limit detected: retry_after={s}s rpm_hint={n} provider={name}` |
| Proactive throttling | WARNING | Includes "consecutive timeouts" in reason |
| Middleware init | INFO | Existing, shows all config values |

---

## Testing

### Unit Tests

1. `test_extract_rate_limit_info_dashscope()` - Mock Dashscope 429 response
2. `test_extract_rate_limit_info_zhipu()` - Mock Zhipu 429 response
3. `test_extract_rate_limit_info_headers()` - Standard retry-after header
4. `test_adjust_rpm_limit_logging()` - Verify log output format
5. `test_adjust_rpm_limit_bounds()` - Min 5, max 10000 validation
6. `test_adjust_rpm_limit_no_change()` - Same value skips adjustment
7. `test_consecutive_timeout_proactive_throttling()` - RPM reduced after 2 timeouts
8. `test_config_defaults_enabled()` - New default values verified
9. `test_provider_detection_from_message()` - Dashscope/Zhipu name extraction

### Integration Test

- `test_429_error_runtime_rpm_adjustment()` - Simulate 429, verify RPM changes

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Provider doesn't communicate RPM limit | Use retry-after only, no permanent adjustment |
| Over-aggressive throttling | Minimum RPM bound of 5, only reduce on confirmed signals |
| Thread budget redistribution race | Use existing async lock in `_redistribute_budgets()` |
| False positive timeout throttling | Only trigger after 2+ consecutive timeouts |

---

## Implementation Order

1. Update `LLMRateLimitConfig` defaults in `models.py`
2. Update `config/config.template.yml` and `config/develop/config.yml`
3. Add `_extract_rate_limit_info()` function in `llm_rate_limit.py`
4. Add `adjust_rpm_limit()` method in `LLMRateLimitMiddleware`
5. Integrate into `awrap_model_call()` 429 and timeout handling
6. Add unit tests
7. Run `./scripts/verify_finally.sh`

---

## Success Criteria

1. Rate limiting enabled by default after restart
2. 429 errors logged with provider info
3. RPM adjustments logged with before/after values
4. No timeouts when provider rate limits are respected
5. All tests pass