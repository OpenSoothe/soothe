# BM-003: AI-Driven Daemon Endpoint Benchmark

> **Purpose**: Validate daemon HTTP REST endpoints with AI-style workload patterns, including endpoint health, thread lifecycle, and response latency budgets.
>
> **Last Updated**: 2026-04-16
>
> **Status**: Active

---

## Overview

This benchmark evaluates daemon endpoint behavior under realistic prompt-driven interactions:

1. Baseline service health and protocol metadata checks.
2. Thread creation and retrieval via HTTP REST.
3. AI-driven continuation flow using `/resume` with prompt-like messages.
4. History verification to ensure user prompt persistence.
5. Lifecycle cleanup through archive/delete operations.

---

## Endpoint Coverage

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/health` | GET | Transport health |
| `/api/v1/status` | GET | Runtime status |
| `/api/v1/version` | GET | Protocol/version contract |
| `/api/v1/threads` | POST | Thread creation |
| `/api/v1/threads/{thread_id}` | GET | Thread fetch |
| `/api/v1/threads/{thread_id}/resume` | POST | AI prompt continuation |
| `/api/v1/threads/{thread_id}/messages` | GET | Prompt persistence check |
| `/api/v1/threads/{thread_id}` | DELETE | Archive/delete cleanup |

---

## Test Cases

### TC-001: Daemon Health Baseline

**Request**: `GET /api/v1/health`

**Expected Behavior**:
- Returns HTTP 200
- Response includes `status=healthy`
- Response includes `transport=http_rest`

**Verification Conditions**:
- [ ] Status code is 200
- [ ] `status` field equals `healthy`
- [ ] Endpoint responds under 1.5s

---

### TC-002: Daemon Status Contract

**Request**: `GET /api/v1/status`

**Expected Behavior**:
- Returns HTTP 200
- Response includes `status=running`
- Response includes `transport=http_rest`

**Verification Conditions**:
- [ ] Status code is 200
- [ ] `status` field equals `running`
- [ ] `transport` field equals `http_rest`
- [ ] Endpoint responds under 1.5s

---

### TC-003: Version and Protocol Contract

**Request**: `GET /api/v1/version`

**Expected Behavior**:
- Returns HTTP 200
- Response includes protocol string

**Verification Conditions**:
- [ ] Status code is 200
- [ ] `protocol` field exists and is non-empty
- [ ] Endpoint responds under 1.5s

---

### TC-004: Create Thread for AI Prompting

**Request**: `POST /api/v1/threads`

**Payload**:
```json
{
  "initial_message": "Benchmark bootstrap message for daemon endpoint validation.",
  "metadata": {
    "tags": ["benchmark", "bm-003", "ai-driven"],
    "priority": "normal"
  }
}
```

**Expected Behavior**:
- Returns HTTP 200
- Response includes `thread_id`

**Verification Conditions**:
- [ ] Status code is 200
- [ ] `thread_id` exists and is non-empty
- [ ] Endpoint responds under 2.0s

---

### TC-005: Resume Thread with AI-style Prompt

**Request**: `POST /api/v1/threads/{thread_id}/resume`

**Payload**:
```json
{
  "message": "Summarize the purpose of this daemon benchmark in one sentence."
}
```

**Expected Behavior**:
- Returns HTTP 200
- Response includes `status=resumed`
- Response thread id matches created thread

**Verification Conditions**:
- [ ] Status code is 200
- [ ] `status` equals `resumed`
- [ ] `thread_id` matches created thread id
- [ ] Endpoint responds under 2.5s

---

### TC-006: Verify Prompt Persistence in Message History

**Request**: `GET /api/v1/threads/{thread_id}/messages?limit=50&offset=0`

**Expected Behavior**:
- Returns HTTP 200
- Thread history contains at least one user message
- Thread history contains benchmark prompt content

**Verification Conditions**:
- [ ] Status code is 200
- [ ] `messages` is an array
- [ ] At least one message with `role=user` exists
- [ ] One user message contains `Summarize the purpose of this daemon benchmark`
- [ ] Endpoint responds under 3.0s

---

### TC-007: Cleanup via Archive then Delete

**Requests**:
- `DELETE /api/v1/threads/{thread_id}?archive=true`
- `DELETE /api/v1/threads/{thread_id}?archive=false`

**Expected Behavior**:
- Archive returns `status=archived`
- Delete returns `status=deleted`

**Verification Conditions**:
- [ ] Archive request status code is 200
- [ ] Archive response status is `archived`
- [ ] Delete request status code is 200
- [ ] Delete response status is `deleted`
- [ ] Combined cleanup under 2.0s

---

## Execution Instructions

### Prerequisites

```bash
# Ensure daemon is running with HTTP REST enabled
uv run soothe daemon start --config config.dev.yml

# Verify endpoint is reachable
curl http://127.0.0.1:8766/api/v1/health
```

### Automated Runner

```bash
uv run python benchmarks/run_bm003_daemon_endpoint.py --base-url http://127.0.0.1:8766
```

Optional flags:

```bash
uv run python benchmarks/run_bm003_daemon_endpoint.py \
  --base-url http://127.0.0.1:8766 \
  --timeout 10 \
  --history-poll-timeout 12 \
  --json
```

---

## Success Criteria

Benchmark run is considered successful when:

- All test cases pass
- No endpoint latency exceeds its threshold
- Script exits with code `0`

Any failed test case or latency breach should return non-zero exit code.

---

## Failure Modes to Detect

1. Daemon endpoint unreachable or non-200 response.
2. Endpoint contract drift (`status`, `transport`, `protocol` missing/changed unexpectedly).
3. Thread lifecycle breakage (create/resume/messages/archive/delete failures).
4. Prompt persistence regression (user message not retained).
5. Latency regressions beyond benchmark budgets.

---

## Status Tracking

| Run Date | TC-001 | TC-002 | TC-003 | TC-004 | TC-005 | TC-006 | TC-007 | Notes |
|----------|--------|--------|--------|--------|--------|--------|--------|-------|
| 2026-04-16 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | First successful run - all tests passed, latencies well within budget |
| 2026-04-16 | 🔍 | 🔍 | 🔍 | 🔍 | 🔍 | 🔍 | 🔍 | Initial benchmark definition |

