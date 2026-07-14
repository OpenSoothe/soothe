# IG-301: Adaptive LLM per-call timeout

## Problem

Goal-completion synthesis builds very large prompts (~75K+ chars). The rate-limit middleware used a fixed `asyncio.wait_for(..., timeout=60)`, so synthesis streams were cancelled mid-output with `TimeoutError`.

## Solution

1. **`ExecutionConfig`**: Add `llm_call_timeout_adaptive` (default `true`) and `llm_call_timeout_max_seconds` (default `600`, clamped 60–3600).
2. **`LLMRateLimitMiddleware`**: Estimate input size from `ModelRequest` (system message + message contents), then use  
   `effective = min(max_cap, max(base, base + prompt_chars // 400))`.  
   Ratio 400 chars per extra second keeps small calls near `base` while scaling synthesis.
3. **Config template + dev overlay**: Document new keys next to `llm_call_timeout_seconds`.

## Verification

`./scripts/verify_finally.sh`
