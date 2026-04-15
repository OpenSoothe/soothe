# IG-179: AI-Driven Daemon Endpoint Benchmarks

> **Status**: In Progress
>
> **Created**: 2026-04-16
>
> **Owner**: AI Agent

---

## Overview

Add a new benchmark artifact and executable runner to validate Soothe daemon HTTP REST endpoints with AI-style prompts and measurable latency checks.

This guide introduces:

1. A new benchmark spec file under `benchmarks/` for daemon endpoint verification.
2. A Python benchmark runner that executes endpoint checks and thread lifecycle flows.
3. README updates so the benchmark is discoverable and easy to run.

---

## Goals

- Add `BM-003` benchmark coverage for daemon endpoint behavior.
- Make benchmark execution scriptable and repeatable.
- Validate both correctness and timing thresholds for core daemon APIs.

---

## Scope

### In Scope

- `benchmarks/BM-003-ai-driven-daemon-endpoint.md`
- `benchmarks/run_bm003_daemon_endpoint.py`
- `benchmarks/README.md` updates for benchmark registration and run instructions

### Out of Scope

- Changes to daemon runtime endpoint implementations
- New transport protocol features
- CI pipeline integration for benchmarks

---

## Implementation Steps

1. Define BM-003 test cases against `/api/v1/health`, `/api/v1/status`, `/api/v1/version`, and thread endpoints.
2. Implement benchmark runner using `httpx` with pass/fail assertions and latency measurements.
3. Add aggregate summary output and non-zero exit code when checks fail.
4. Update benchmark index documentation.

---

## Validation

- Run BM-003 runner against a running daemon HTTP REST endpoint.
- Ensure benchmark output includes per-test latency and pass/fail status.
- Confirm process exit code is `0` when all checks pass, non-zero otherwise.

---

## Rollback Plan

- Remove `BM-003` benchmark file and runner script.
- Revert `benchmarks/README.md` benchmark table and execution instructions.

