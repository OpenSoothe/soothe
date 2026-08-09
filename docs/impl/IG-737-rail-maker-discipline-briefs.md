# IG-737: Rail maker discipline briefs (TDD, debug, parallel, worktrees)

## Goal

Encode Superpowers-aligned discipline into LoopRail goal briefs so Autopilot
makers/scouts/planners follow TDD, systematic debugging, independent-domain
parallelism, and explicit `using-git-worktrees` skill invocation (soothe-nano
builtin).

## Status

Done.

## Scope

- [x] Shared SoT fragments in `soothe.rails.verb_defaults`
- [x] Wire into `RailBuiltinExecutor` (decompose, plan_and_implement, makers,
      QA, feedback, retry_maker) and planner `do:` recipes
- [x] Strengthen `feature-dev` conditions; bump `greenfield-system` summary
- [x] Unit tests + builtin rails README note
- [x] Verify (`./scripts/verify_finally.sh`)

## Cleanse

- [x] Collapse spawn/retry maker copy into `slice_maker_brief`; drop superseded
      “Work in workspace isolation” line (covered by `using-git-worktrees` SoT)
- [x] Document that efficiency + parallel-dispatch blocks must not be duplicated
      in rail YAML (appended by `apply_planner_waveplan_hints`)

## Out of scope

- Distilling TDD/debug/dispatch into nano builtin skills
- Host `worktree_ops` path changes
- Structured completion fields / report-commit judge changes
