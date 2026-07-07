# IG-379: Local plan step ids, dependency resolution, dependency-mode observability

**Status:** Completed  
**Scope:** `assign_plan_step_ids`, `Executor._execute_dependency`

## Motivation

Models emit short local step ids (`01`, `02`) and `dependencies` that may use a different numeric spelling (`1` vs `01`). `id_map.get(dep, dep)` left those deps unresolved, so `get_ready_steps` never scheduled downstream work. Operators also lacked logs when dependency mode stopped with steps never started.

## Changes

| Area | Change |
|------|--------|
| `schemas.py` | `_resolve_in_plan_dependency`: map dependency strings to in-plan composites via exact raw id, single-candidate digit-normalization (`int` equality), or single case-insensitive raw-id match; otherwise leave unchanged (external refs per IG-346). |
| `executor.py` | After dependency-mode loop, log a warning listing never-started steps and their deps still not in `local_done`. |
| Prompts | `execution_policies.xml` + `plan_generate_instructions.xml`: require stable local ids and `dependencies` that reference those ids (numeric alias tolerated at remap time). |
| Tests | `test_schemas.py` for digit-alias remap; `test_executor_dependency_residual_log_ig379.py` for caplog. |

## Verification

```bash
./scripts/verify_finally.sh
```

## References

- IG-303, IG-346, RFC-201
