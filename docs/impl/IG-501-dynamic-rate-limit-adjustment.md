# IG-501: Dynamic LLM Rate Limit Adjustment

**Status**: Completed
**Depends on**: IG-499 (rate limit retry infrastructure)
**Related Design**: `docs/drafts/2026-06-19-dynamic-llm-rate-limit-design.md`

---

## Summary

Enable LLM rate limiting by default with runtime RPM adjustment based on provider feedback (Dashscope/Zhipu 429 errors and consecutive timeouts).

---

## Scope

### In Scope
- Enable `LLMRateLimitMiddleware` by default with moderate settings
- Extract rate limit info from provider 429 responses (retry-after, RPM hints, provider detection)
- Runtime RPM adjustment with logging
- Proactive throttling after consecutive timeouts
- Config sync (template + dev)

### Out of Scope
- Config file modification at runtime
- TPM limiting
- Provider-specific static profiles

---

## Implementation Steps

### Step 1: Configuration Defaults
- [ ] Update `LLMRateLimitConfig` in `models.py`: `enabled=True`, `rpm_limit=60`, `concurrent_limit=8`, `call_timeout_seconds=150`
- [ ] Update `config/config.template.yml` with new defaults and rationale comment
- [ ] Update `config/config.dev.yml` with matching structure

### Step 2: Rate Limit Info Extraction
- [ ] Add `_extract_rate_limit_info()` function in `llm_rate_limit.py`
- [ ] Extract: retry_after_seconds, rpm_limit_hint, provider_name
- [ ] Handle Dashscope/Zhipu response body formats
- [ ] Detect provider from error message content

### Step 3: Runtime RPM Adjustment
- [ ] Add `adjust_rpm_limit()` method to `LLMRateLimitMiddleware`
- [ ] Validate bounds (min 5, max 10000)
- [ ] Log adjustment with before/after/reason
- [ ] Trigger `_redistribute_budgets()` for thread budgets

### Step 4: Retry Flow Integration
- [ ] Integrate `_extract_rate_limit_info()` call after 429 detection
- [ ] Call `adjust_rpm_limit()` if provider gives RPM hint
- [ ] Add proactive throttling after 2+ consecutive timeouts (reduce 20%)
- [ ] Add warning logs for rate limit detection

### Step 5: Testing
- [ ] Unit tests for `_extract_rate_limit_info()` with mocked responses
- [ ] Unit tests for `adjust_rpm_limit()` bounds and logging
- [ ] Unit test for consecutive timeout proactive throttling
- [ ] Unit test for new config defaults
- [ ] Run `./scripts/verify_finally.sh`

---

## Files Changed

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/config/models.py` | Update `LLMRateLimitConfig` defaults |
| `config/config.template.yml` | Sync defaults with rationale |
| `config/config.dev.yml` | Sync with template |
| `packages/soothe/src/soothe/middleware/llm_rate_limit.py` | New function, new method, integration |
| `packages/soothe/tests/unit/middleware/test_llm_rate_limit.py` | New unit tests (extend existing) |

---

## Verification

1. `make lint` passes
2. All unit tests pass
3. `./scripts/verify_finally.sh` passes
4. Manual: restart daemon, verify rate limiting enabled by default in logs

---

## Estimated Effort

~2-3 hours implementation + testing