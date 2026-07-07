# IG-318: OperationSecurityProtocol Implementation

**Status**: In Progress  
**RFC**: RFC-617  
**Created**: 2026-04-30

## Scope

Implement unified operation-level security for workspace file operations and execution tools:

1. Add `OperationSecurityProtocol` and decision/request/context models.
2. Add `WorkspaceToolOperationSecurity` implementation for:
   - Filesystem path and file-type checks (aligned with IG-300 behavior).
   - Command safety checks for command-bearing execution tools.
3. Integrate operation security into `ConfigDrivenPolicy.check()` before permission matching.
4. Add unit tests validating operation-security decisions in policy checks.

## Design Notes

- Keep existing `PolicyProtocol` contract and profile semantics unchanged.
- Use tool metadata registry for operation-kind and path extraction where possible.
- Ensure dynamic workspace (`PolicyContext.workspace`) remains the first boundary source.
- Keep tool-local guardrails as defense in depth; policy-level enforcement becomes consistent.

## Checklist

- [ ] Add protocol file in `packages/soothe/src/soothe/protocols/operation_security.py`.
- [ ] Export new protocol symbols from `packages/soothe/src/soothe/protocols/__init__.py`.
- [ ] Add implementation in `packages/soothe/src/soothe/core/security/operation_security.py`.
- [ ] Update `ConfigDrivenPolicy` to call operation-security evaluation.
- [ ] Add/adjust unit tests under `packages/soothe/tests/unit/backends/policy/`.
- [ ] Run targeted tests.
- [ ] Run `./scripts/verify_finally.sh`.
