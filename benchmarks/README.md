# Soothe Benchmarks

This directory contains benchmarks for validating Soothe agent behavior and performance.

## Purpose

Benchmarks serve as:
- **Verification** for AI agents to validate runtime behavior
- **Regression tests** to catch workspace/context issues
- **Performance baselines** for execution time expectations

## Structure

Each benchmark file follows this format:

```
BM-NNN-brief-title.md
├── Overview
├── Test Cases (TC-NNN)
│   ├── Query
│   ├── Expected Behavior
│   ├── Verification Conditions
│   └── Success Criteria
├── Execution Instructions
└── Status Tracking
```

## Available Benchmarks

| ID | Title | Purpose | Latest Status |
|----|-------|---------|---------------|
| [BM-001](BM-001-workspace-injection.md) | Workspace Injection | Verify workspace context propagation | ✅ Pass (virtual filesystem "/" maps client workspace) |
| [BM-002](BM-002-subagent-selection.md) | Subagent Selection | Verify slash-command routing and passthrough behavior | ✅ Pass (TC-001-007 verified) |
| [BM-003](BM-003-ai-driven-daemon-endpoint.md) | Daemon HTTP REST Endpoint | Verify HTTP REST daemon endpoints | ✅ Pass (all 7 endpoints working) |
| [BM-004](BM-004-security-verification.md) | Security Verification | Verify operation-level security checks | 🔍 Needs runner script |
| [BM-005](BM-005-baseline-non-tui-cases.md) | Baseline Non-TUI Cases | Basic functionality and performance | ✅ Pass (4/4 cases, ~23:35 total) |

## Running Benchmarks

### Manual Execution

```bash
# Run a specific test case
uv run soothe --no-tui -p "<query from test case>"

# Verify conditions in output
```

### BM-003: Daemon HTTP REST Endpoints

```bash
# Ensure daemon is running
uv run soothed start --config config/develop/config.yml

# Test endpoints
curl -s http://127.0.0.1:8766/api/v1/health
curl -s http://127.0.0.1:8766/api/v1/status
curl -s http://127.0.0.1:8766/api/v1/version
curl -s http://127.0.0.1:8766/api/v1/config
curl -s http://127.0.0.1:8766/api/v1/autopilot/goals
```

> **Note**: Conversation control uses WebSocket loop protocol (IG-408). HTTP REST provides health, status, config, and autopilot endpoints only.

## Adding New Benchmarks

1. Create `BM-NNN-brief-title.md`
2. Define test cases with:
   - Query (what to ask)
   - Expected behavior
   - Verification conditions (checklist)
   - Success criteria (pass/fail conditions)
3. Add execution instructions
4. Update this README

## Benchmark Naming Convention

- **BM-NNN**: Benchmark number (001-999)
- **TC-NNN**: Test case within benchmark
- **VC-NNN**: Verification condition (optional)

## Status Icons

- ✅ Pass
- ❌ Fail
- ⚠️ Partial
- 🔍 Needs Review
- ⏱️ Timeout