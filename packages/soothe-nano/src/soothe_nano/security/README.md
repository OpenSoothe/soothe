# `soothe_nano.security`

Security utilities in `soothe-nano` are organized by concern and exposed
through a small public API.

## Layout

- `security_api.py`
  - Canonical public API exports
- `path_security.py`
  - Path validation + normalization (`PathValidator`, `ValidationResult`)
- `policy_models.py`
  - Policy data models and evaluation (`SecurityPolicy`, `PolicyDecision`, `PolicyViolation`)
- `policy_profiles.py`
  - Predefined policy constants + profile-driven policy (`ConfigDrivenPolicy`)
- `operation_guard.py`
  - Runtime operation checks (`WorkspaceToolOperationSecurity`)
- `security_enforcer.py`
  - Enforcement orchestration (`SecurityEnforcer`, `SecurityError`, `SecurityContext`)

## Recommended imports

```python
from soothe_nano.security import (
    ConfigDrivenPolicy,
    PathValidator,
    SecurityEnforcer,
    WorkspaceToolOperationSecurity,
)
from soothe_nano.security.policy_models import SecurityPolicy
from soothe_nano.security.policy_profiles import STRICT_POLICY
```

## Typical usage

```python
from soothe_nano.security import SecurityEnforcer
from soothe_nano.security.policy_profiles import STRICT_POLICY

enforcer = SecurityEnforcer(workspace="/safe/workspace", policy=STRICT_POLICY)
decision = enforcer.check_access("src/config.yml", "read")

if decision.is_denied:
    raise RuntimeError(decision.reason)
```
