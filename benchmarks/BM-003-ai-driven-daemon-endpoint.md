# BM-003: Daemon HTTP REST Endpoint Benchmark

> **Purpose**: Validate daemon HTTP REST endpoints for health, status, version, configuration, and autopilot goal management.
>
> **Last Updated**: 2026-05-09
>
> **Status**: Active

---

## Overview

This benchmark evaluates daemon endpoint behavior for:

1. Baseline service health and protocol metadata checks.
2. Configuration retrieval and schema validation.
3. Autopilot goal lifecycle (submit, list, approve/reject).
4. Autopilot wake/dream state management.

---

## Endpoint Coverage

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/health` | GET | Transport health |
| `/api/v1/status` | GET | Runtime status |
| `/api/v1/version` | GET | Protocol/version contract |
| `/api/v1/config` | GET | Current configuration |
| `/api/v1/config/schema` | GET | Configuration schema |
| `/api/v1/autopilot/status` | GET | Autopilot state |
| `/api/v1/autopilot/goals` | GET | List pending goals |
| `/api/v1/autopilot/submit` | POST | Submit new goal |
| `/api/v1/autopilot/goals/{goal_id}` | GET | Get specific goal |
| `/api/v1/autopilot/goals/{goal_id}/approve` | POST | Approve goal |
| `/api/v1/autopilot/goals/{goal_id}/reject` | POST | Reject goal |
| `/api/v1/autopilot/wake` | POST | Wake autopilot |
| `/api/v1/autopilot/dream` | POST | Dream autopilot |
| `/api/v1/autopilot/inbox` | GET | Get inbox items |

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

### TC-004: Configuration Retrieval

**Request**: `GET /api/v1/config`

**Expected Behavior**:
- Returns HTTP 200
- Response includes configuration object

**Verification Conditions**:
- [ ] Status code is 200
- [ ] Response body is valid JSON
- [ ] Endpoint responds under 1.5s

---

### TC-005: Configuration Schema

**Request**: `GET /api/v1/config/schema`

**Expected Behavior**:
- Returns HTTP 200
- Response includes schema definition

**Verification Conditions**:
- [ ] Status code is 200
- [ ] Response body is valid JSON schema
- [ ] Endpoint responds under 1.5s

---

### TC-006: Autopilot Status

**Request**: `GET /api/v1/autopilot/status`

**Expected Behavior**:
- Returns HTTP 200
- Response includes autopilot state information

**Verification Conditions**:
- [ ] Status code is 200
- [ ] Response body is valid JSON
- [ ] Endpoint responds under 1.5s

---

### TC-007: Autopilot Goals List

**Request**: `GET /api/v1/autopilot/goals`

**Expected Behavior**:
- Returns HTTP 200
- Response includes goals array

**Verification Conditions**:
- [ ] Status code is 200
- [ ] Response body contains `goals` array (may be empty)
- [ ] Endpoint responds under 1.5s

---

## Execution Instructions

### Prerequisites

```bash
# Ensure daemon is running with HTTP REST enabled
uv run soothed start --config config/config.dev.yml

# Verify endpoint is reachable
curl http://127.0.0.1:8766/api/v1/health
```

### Manual Execution

```bash
# TC-001: Health check
curl -s http://127.0.0.1:8766/api/v1/health

# TC-002: Status check
curl -s http://127.0.0.1:8766/api/v1/status

# TC-003: Version check
curl -s http://127.0.0.1:8766/api/v1/version

# TC-004: Config retrieval
curl -s http://127.0.0.1:8766/api/v1/config

# TC-005: Config schema
curl -s http://127.0.0.1:8766/api/v1/config/schema

# TC-006: Autopilot status
curl -s http://127.0.0.1:8766/api/v1/autopilot/status

# TC-007: Autopilot goals
curl -s http://127.0.0.1:8766/api/v1/autopilot/goals
```

### Automated Runner (TODO)

```bash
# Future: Python runner script
uv run python benchmarks/run_bm003_daemon_endpoint.py --base-url http://127.0.0.1:8766
```

---

## Success Criteria

Benchmark run is considered successful when:

- All test cases pass
- No endpoint latency exceeds its threshold
- All responses are valid JSON

Any failed test case or latency breach should return non-zero exit code.

---

## Failure Modes to Detect

1. Daemon endpoint unreachable or non-200 response.
2. Endpoint contract drift (`status`, `transport`, `protocol` missing/changed unexpectedly).
3. Configuration endpoints return invalid JSON.
4. Autopilot endpoints fail to respond.

---

## Status Tracking

| Run Date | TC-001 | TC-002 | TC-003 | TC-004 | TC-005 | TC-006 | TC-007 | Notes |
|----------|--------|--------|--------|--------|--------|--------|--------|-------|
| 2026-05-09 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | All endpoints working; TC-006 autopilot/status now returns `state=idle` (fixed 500 error) |
| 2026-05-09 | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | TC-006 autopilot/status returns 500; other endpoints work |
| 2026-05-09 | ✅ | ✅ | ✅ | 🔍 | 🔍 | 🔍 | 🔍 | Updated to match current daemon API (removed /threads endpoints, added /autopilot) |
| 2026-04-16 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Original test failed: /threads endpoints don't exist in current API |

