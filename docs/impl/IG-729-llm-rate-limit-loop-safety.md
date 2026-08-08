# IG-729: LLM rate-limit loop-safety + global concurrency (consume)

**Status**: done  
**Package**: `soothe` / `soothe-nano` (consume); engine fix in `soothe-deepagents` 0.8.5

## Problem

Multi-worker LLM calls shared process-wide `asyncio.Semaphore` / `asyncio.Lock` in
`soothe_deepagents.middleware.llm_rate_limit`, causing
`RuntimeError: Semaphore is bound to a different event loop` and empty-output
model-call failures. Per-budget concurrency alone also allowed N×limit in-flight
calls and provider concurrency 429s.

## Scope (this repo)

1. Bump `soothe-deepagents` to `>=0.8.5`.
2. Add `LLMRateLimitConfig.global_concurrent_limit` and wire it through nano
   middleware builder as `max_concurrent_requests_global`.
3. Sync `config/nano.template.yml` and daemon `setup/templates/nano.yml`.
4. Default `global_concurrent_limit: 0` (no process-wide cap); positive values
   remain a hard cap. Per-budget `concurrent_limit` still applies.

## Upstream

`soothe-deepagents` 0.8.5 ([release](https://github.com/mirasoth/soothe-deepagents/releases/tag/v0.8.5)):

- Loop-local per-budget semaphores
- Threading-safe registry
- Process-wide `CrossLoopSemaphore` global slots (`0` = unlimited)
- Concurrency/throttling 429 shrinks a finite global cap (unlimited left alone)

## Verification

- deepagents CI + PyPI publish for 0.8.5
- soothe: path source removed; `uv.lock` / nano lock pin `0.8.5`;
  `./scripts/verify_finally.sh`

## Cleanse (follow-up)

- `llm_rate_limit_config_from` stopped reading removed `agent.loop.llm_rate_limit`
  and now resolves `agent.middleware.llm_rate_limit` (so direct LLM paths honor
  configured timeouts/retries/`global_concurrent_limit`).
- Wiki / IG-709 paths updated off the legacy `agent.loop` rate-limit keys.
