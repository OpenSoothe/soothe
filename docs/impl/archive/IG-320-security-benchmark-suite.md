# IG-320: Security Benchmark Suite (BM-004)

**Status**: In Progress  
**Created**: 2026-04-30

## Scope

Add a dedicated benchmark for security verification under `benchmarks/`:

1. Create `BM-004-security-verification.md` with reproducible security test cases.
2. Add an automated benchmark runner `run_bm004_security_verification.py`.
3. Register BM-004 in `benchmarks/README.md`.

## Focus Areas

- Filesystem boundary enforcement (workspace containment)
- Denied path pattern enforcement
- File type approval flow
- Execution command blocking parity for command-bearing tools

## Validation

- Benchmark runner exits `0` when all checks pass, `1` on any failed assertion.
- Runner supports JSON output for CI integration.
