# IG-626: Security Flat Module Layout

## Goal

Clarify `soothe_nano.security` by using a flat, semantically named module layout
with balanced file sizes and no nested subpackages.

## Scope

- Replace legacy module names:
  - `validator.py` -> `path_security.py`
  - `policy.py` -> `policy_models.py` + `policy_profiles.py`
  - `operation_security.py` -> `operation_guard.py`
  - `enforcement.py` -> `security_enforcer.py`
  - `config_policy.py` -> merged into `policy_profiles.py`
- Add `security_api.py` as canonical export surface.
- Update all in-repo imports to new module paths.
- Remove legacy modules (no backward compatibility shims).

## Design

- `path_security.py`
  - Path validation, normalization, validator factories, validation result/error types.
- `policy_models.py`
  - Core policy enums, decision/violation data models, `SecurityPolicy` evaluation.
- `policy_profiles.py`
  - Predefined policy constants + profile-driven permission policy.
- `operation_guard.py`
  - Filesystem and shell command operation security evaluation.
- `security_enforcer.py`
  - Enforcement orchestration, rate limiting, audit records, context manager, errors.
- `security_api.py`
  - Single explicit export hub for package-level imports.

## Verification

- Run `./scripts/verify_finally.sh` after migration.
- Fix any import fallout in tests/examples/toolkits to reference the new module names.
