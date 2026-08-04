# SOJ-05: Configuration Security Audit Report

> Audit of security-relevant defaults and threshold tuning across all Soothe configuration surfaces.

**Date:** 2026-08-04
**Step:** SOJ-05
**Status:** Complete — all patches applied, `./scripts/verify_finally.sh` green

---

## Scope

Configuration surfaces audited:

| Surface | File | Synced Copies |
|---------|------|---------------|
| Nano template | `config/nano.template.yml` | `packages/soothe-daemon/src/soothe_daemon/setup/templates/nano.yml` |
| Soothe host template | `config/soothe.template.yml` | `packages/soothe-daemon/src/soothe_daemon/setup/templates/soothe.yml` |
| Daemon template | `config/daemon.template.yml` | `packages/soothe-daemon/src/soothe_daemon/setup/templates/daemon.yml` |
| Soothe config models | `packages/soothe/src/soothe/config/models.py` | — |
| Soothe config constants | `packages/soothe/src/soothe/config/constants.py` | — |
| Daemon config settings | `packages/soothe-daemon/src/soothe_daemon/config/settings.py` | — |
| Develop profile | `config/develop/nano.yml` | — (no overrides needed) |

---

## Findings & Patches

### 1. `allow_dangerous_requests: true` (CRITICAL — SSRF vector)

**Risk:** High. The HTTP requests toolkit (`requests_get`, `requests_post`, etc.) was enabled with `allow_dangerous_requests: true` by default in the nano template. This permits the agent to make arbitrary outbound HTTP requests (POST, PUT, DELETE) to any URL — including internal network addresses — without operator opt-in. This is a Server-Side Request Forgery (SSRF) vector.

**Old default:** `true`
**New default:** `false` (operator must explicitly opt in)

**Files patched:**
- `config/nano.template.yml` line 171
- `packages/soothe-daemon/src/soothe_daemon/setup/templates/nano.yml` line 171

**Note:** The Pydantic model default in `soothe_nano.config.models.HttpRequestsConfig` remains `True` because LangChain requires it to construct the toolkit. The template default is the authoritative operator-facing default; the model default is a construction-time gate. Operators who want HTTP request tools must set `allow_dangerous_requests: true` explicitly in their config.

---

### 2. `DEFAULT_MAX_TOOL_CALLS_PER_STEP: 999` (HIGH — resource exhaustion)

**Risk:** High. The per-execute-step cap on tool results consumed from the CoreAgent Act stream was 999 — effectively unlimited. A runaway tool loop (e.g., recursive subagent delegation, infinite file reads) could consume massive context, tokens, and wall-clock time before hitting the cap.

**Old default:** `999`
**New default:** `100`

**Rationale:** 100 tool results per execute step is sufficient for complex multi-tool workflows (typical steps use 5-20 tools). The cap bounds cost and resource exhaustion. Operators who need more can raise it up to the model's `le=10_000` ceiling.

**Files patched:**
- `packages/soothe/src/soothe/config/constants.py` line 33 (`DEFAULT_MAX_TOOL_CALLS_PER_STEP = 100`)
- `config/soothe.template.yml` line 66 (`max_tool_calls_per_step: 100`)
- `packages/soothe-daemon/src/soothe_daemon/setup/templates/soothe.yml` line 66

**Propagation:** The constant is re-exported as `_DEFAULT_MAX_TOOL_CALLS_PER_STEP` in `step_wave_types.py` and consumed by `executor.py` — both pick up the new value automatically.

---

### 3. `dispatch_timeout_seconds: 0` (MEDIUM — runaway dispatch)

**Risk:** Medium. The dispatch watchdog monitors CoreAgent graph stream inactivity during Execute. A value of `0` disables it entirely — a stalled stream (e.g., hung LLM call, deadlocked tool) runs indefinitely, consuming a worker slot and thread indefinitely. This is especially dangerous in the thread_pool mode where a stalled thread reduces pool capacity.

**Old default:** `0.0` (disabled)
**New default:** `600.0` (10 minutes)

**Rationale:** 600 seconds (10 min) is a safe default that bounds runaway dispatches while accommodating legitimate long tool executions (e.g., `browser_use` has a 1800s timeout, but the watchdog monitors stream *inactivity*, not total duration — heartbeats keep it alive). Operators who need longer can raise it.

**Files patched:**
- `packages/soothe/src/soothe/config/models.py` line 966-975 (field default + description)
- `config/soothe.template.yml` line 67 (`dispatch_timeout_seconds: 600`)
- `packages/soothe-daemon/src/soothe_daemon/setup/templates/soothe.yml` line 67

**Edge case:** When `Executor` is constructed with `config=None` (unit tests), `_dispatch_timeout_seconds()` returns `0.0` (disabled) — the no-config fallback is unchanged, preserving existing test behavior.

---

### 4. `max_query_duration_minutes: 0` (MEDIUM — unlimited query lifetime)

**Risk:** Medium. The daemon's max query duration was unlimited (0 = no timeout). A runaway or orphaned thread could consume resources indefinitely — a thread that never completes ties up a pool slot, database connections, and memory. In multi-tenant deployments, a single runaway thread can degrade service for all users.

**Old default:** `0` (unlimited)
**New default:** `1440` (24 hours)

**Rationale:** 24 hours is generous for any legitimate long-running query while bounding resource consumption. The `thread_max_age_hours: 24` GC setting aligns with this. Operators who need longer can set `0` (unlimited) explicitly.

**Files patched:**
- `config/daemon.template.yml` line 50
- `packages/soothe-daemon/src/soothe_daemon/setup/templates/daemon.yml` line 50
- `packages/soothe-daemon/src/soothe_daemon/config/settings.py` line 94-98 (field default + description)

---

## Settings Reviewed and Left As-Is (Secure)

| Setting | Current Default | Assessment |
|---------|----------------|------------|
| `security.allow_paths_outside_workspace` | `false` | Correct — workspace sandboxing by default |
| `security.require_approval_for_outside_paths` | `true` | Correct — approval gate for path escape |
| `security.denied_paths` | `/etc/**`, `~/.ssh/**`, `~/.aws/**`, etc. | Correct — system dirs and secrets blocked |
| `security.require_approval_for_file_types` | `.env`, `.pem`, `.key`, `.p12`, `.pfx`, `.crt` | Correct — sensitive file types gated |
| `tools.http_requests.verify_ssl` | `true` | Correct — TLS verification by default |
| `agent.loop.general_purpose_subagent` | `false` (host overlay) | Correct — blocks unrestricted subagent delegation |
| `identity.enabled` | `false` | Acceptable for local dev; production must enable |
| `transports.websocket.tls_enabled` | `false` | Acceptable for localhost bind (`127.0.0.1`); production must enable TLS |
| `transports.websocket.host` | `127.0.0.1` | Correct — localhost-only bind by default |
| `transports.websocket.cors_origins` | `localhost:*`, `127.0.0.1:*` | Correct — localhost-only CORS |
| `agent.loop.llm_rate_limit.enabled` | `true` | Correct — rate limiting on by default |
| `agent.loop.llm_rate_limit.rpm_limit` | `60` | Reasonable — 60 requests/min default |
| `agent.loop.context_overflow_threshold_pct` | `0.80` | Correct — triggers compaction at 80% |
| `agent.loop.context_compaction_target_pct` | `0.60` | Correct — compacts to 60% of limit |
| `loop_gc.enabled` | `true` | Correct — automatic GC |
| `loop_status_reconciliation.enabled` | `true` | Correct — stale loop detection |
| `stale_worker_reap.enabled` | `true` | Correct — dead worker cleanup |
| `auto_cancel_on_startup` | `true` | Correct — prevents orphaned processes |
| `cancel_retry_count` | `3` | Reasonable — 3 cooperative cancel attempts before force kill |
| `agent.autopilot.max_iterations` | `10` | Correct — bounded autopilot |
| `agent.loop.max_iterations` | `99` | Acceptable — upper bound on loop iterations |
| `tool_timeout.enabled` | `true` | Correct — tool-level timeout enforcement |
| `tool_timeout.default_seconds` | `60.0` | Reasonable — 60s default per tool |
| `persistence.default_backend` | `sqlite` | Correct — no backend mixing |

---

## Test Updates

Tests asserting old default values were updated to reflect the new secure defaults (per AGENTS.md Rule 8 — defaults were intentionally changed, not test expectations):

| Test File | Old Assertion | New Assertion |
|-----------|--------------|---------------|
| `tests/unit/core/loop/engine/test_executor_tool_budget.py` | `test_default_max_tool_calls_per_step_is_999` → `== 999` | `test_default_max_tool_calls_per_step_is_100` → `== 100` |
| `tests/unit/config/test_config.py` | `cfg.agent.loop.dispatch_timeout_seconds == 0.0` | `cfg.agent.loop.dispatch_timeout_seconds == 600.0` |

Tests that explicitly override values (e.g., `dispatch_timeout_seconds = 0.01`, `max_query_duration_minutes = 0`) were left unchanged — they test specific scenarios, not defaults.

---

## Verification

```
./scripts/verify_finally.sh
```

Results:
- **uv sync:** passed
- **critical deps:** passed
- **import boundaries:** passed (cli → daemon, soothe ↛ daemon, daemon ↛ cli)
- **format:** soothe, soothe-cli, soothe-daemon — all clean
- **lint:** soothe, soothe-cli, soothe-daemon — all clean
- **vulture:** no dead code
- **asyncapi:** no spec drift
- **tests:** 1048 passed, 6 skipped (soothe + soothe-cli + soothe-daemon)

---

## Summary Table

| # | Setting | Old | New | Risk | Severity |
|---|---------|-----|-----|------|----------|
| 1 | `allow_dangerous_requests` | `true` | `false` | SSRF | Critical |
| 2 | `DEFAULT_MAX_TOOL_CALLS_PER_STEP` | `999` | `100` | Resource exhaustion | High |
| 3 | `dispatch_timeout_seconds` | `0` | `600` | Runaway dispatch | Medium |
| 4 | `max_query_duration_minutes` | `0` | `1440` | Unlimited resource hold | Medium |
