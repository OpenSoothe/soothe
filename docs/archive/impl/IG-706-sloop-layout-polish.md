# IG-706: StrangeLoop Layout Polish + Workflow Tracing

## Goal

Polish `soothe.sloop` with restrained root public API, clearer fragment asset
taxonomy, relocated root orphan modules, and consistent INFO/DEBUG tracing on
main StrangeLoop stage workflows.

## Constraints

- Keep `stages/{preprocess,plan,execute,complete,sidecars}/` nested structure.
- Keep `prompts/fragments/` package; expand XML asset subfolders only (no new
  Python packages under `fragments/`).
- Do not split oversized facades (`executor.py`, `planner.py`, `strange_loop.py`).
- No backward-compat shims for relocated orphans or old fragment paths.

## Fragments taxonomy

```text
prompts/fragments/
  __init__.py
  intake/       # intake classifiers
  plan/         # plan-phase instructions + structured parse
  execute/      # execution policies
```

## Root orphan relocation

| From | To |
|------|----|
| `goal_text.py` | `utils/goal_text.py` |
| `goal_step_guard.py` | `utils/goal_step_guard.py` |
| `intake_task_guard.py` | `utils/intake_task_guard.py` |
| `vision_context.py` | `utils/vision_context.py` |
| `config_keys.py` | `utils/config_keys.py` |
| `subagent_catalog.py` | `utils/subagent_catalog.py` |
| `chitchat_fallbacks.py` | `intention/chitchat_fallbacks.py` |

## Public API

Root `__init__.py` exports only:

- `StrangeLoop`
- `Sloop`

## Workflow tracing checklist

| Workflow | Sites | Level |
|----------|-------|-------|
| Intake | preprocess intake, intention two-pass | INFO route; DEBUG details |
| Plan | assess / evaluate / generate / gather | INFO decision; DEBUG counts |
| Execute | execute / commit / record; executor waves | INFO outcomes; DEBUG tools |
| Sidecars | await_user, delegate | INFO start/end |
| Complete | finalize | INFO terminal |
| Graph | runner, routing, strange_loop | INFO invoke/route; DEBUG config |

Do not log full prompts or large ledgers at INFO.

## Verification

Run `./scripts/verify_finally.sh` after migration; fix until green.
