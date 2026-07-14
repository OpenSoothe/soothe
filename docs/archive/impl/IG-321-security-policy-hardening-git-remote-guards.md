# IG-321: Security Policy Hardening and Git Remote Guards

**Status**: In Progress  
**Created**: 2026-04-30

## Scope

Enhance built-in operation security with stronger defaults and command controls:

1. Add always-denied sensitive system path patterns for filesystem operations.
2. Harden command checks for unrecoverable/destructive write patterns.
3. Allow Git local operations while disallowing remote-effective Git operations.
4. Update default security config values in model + template + dev config.
5. Add unit tests for the new security behavior.

## Goals

- Preserve normal local development workflows.
- Prevent high-impact destructive operations by default.
- Keep policy behavior explicit and testable.

## Checklist

- [ ] Harden operation-security path and command rules.
- [ ] Sync `config/config.yml` and `config/config.dev.yml`.
- [ ] Add/update policy unit tests.
- [ ] Run targeted tests.
- [ ] Run `./scripts/verify_finally.sh`.
