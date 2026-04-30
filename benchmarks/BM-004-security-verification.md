# BM-004: Security Verification Benchmark

> **Purpose**: Validate operation-level security decisions for filesystem and execution tool surfaces.
>
> **Last Updated**: 2026-04-30
>
> **Status**: Active

---

## Overview

This benchmark validates core security controls in the policy pipeline:

1. Workspace boundary denial for outside paths.
2. Explicit denied-path pattern enforcement.
3. File-type approval behavior.
4. Command safety blocking for command-bearing tools (`run_command`, `run_background`).

---

## Test Cases

### TC-001: Deny Path Outside Workspace

**Input**:
- Tool: `read_file`
- Path: `/tmp/security-benchmark-outside.txt`
- Security config: `allow_paths_outside_workspace=false`

**Expected Behavior**:
- Decision verdict is `deny`.
- Reason indicates outside workspace boundary.

**Verification Conditions**:
- [ ] verdict == `deny`
- [ ] reason contains `outside workspace`

---

### TC-002: Deny Explicitly Blocked Path Pattern

**Input**:
- Tool: `read_file`
- Path: `~/.ssh/id_rsa`
- Security config includes `~/.ssh/**` in denied paths.

**Expected Behavior**:
- Decision verdict is `deny`.
- Reason indicates denied pattern match.

**Verification Conditions**:
- [ ] verdict == `deny`
- [ ] reason contains `denied pattern`

---

### TC-003: Require Approval for Sensitive File Type

**Input**:
- Tool: `read_file`
- Path: `<workspace>/certs/server.pem`
- Security config includes `.pem` in approval-required file types.

**Expected Behavior**:
- Decision verdict is `need_approval`.
- Reason indicates file-type approval.

**Verification Conditions**:
- [ ] verdict == `need_approval`
- [ ] reason contains `requires approval`

---

### TC-004: Block Dangerous Command in run_command

**Input**:
- Tool: `run_command`
- Command: `rm -rf /`

**Expected Behavior**:
- Decision verdict is `deny`.
- Reason indicates command blocked by security rule.

**Verification Conditions**:
- [ ] verdict == `deny`
- [ ] reason contains `Command blocked`

---

### TC-005: Block Dangerous Command in run_background

**Input**:
- Tool: `run_background`
- Command: `sudo rm -rf /`

**Expected Behavior**:
- Decision verdict is `deny`.
- Reason indicates command blocked by security rule.

**Verification Conditions**:
- [ ] verdict == `deny`
- [ ] reason contains `Command blocked`

---

## Execution Instructions

### Automated Runner

```bash
uv run python benchmarks/run_bm004_security_verification.py
```

Optional JSON output:

```bash
uv run python benchmarks/run_bm004_security_verification.py --json
```

---

## Success Criteria

Benchmark run is successful when:

- All test cases pass.
- Script exits with code `0`.

Any failed test case should return non-zero exit code.

---

## Status Tracking

| Run Date | TC-001 | TC-002 | TC-003 | TC-004 | TC-005 | Notes |
|----------|--------|--------|--------|--------|--------|-------|
| 2026-04-30 | 🔍 | 🔍 | 🔍 | 🔍 | 🔍 | Initial benchmark definition |
