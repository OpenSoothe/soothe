# IG-687: `greenfield-system` LoopRail

**Created**: 2026-08-05  
**Status**: Implemented  
**Related**: [IG-678](IG-678-autopilot-ce-rails-production-readiness.md),
LoopRail design draft, RFC-222

---

## Goal

Ship a built-in LoopRail for **greenfield multi-module system builds**
(compiler scaffold, new platform, multi-crate product) that differs from
`feature-dev` by encoding:

1. Milestone / architecture plan (not vague dual scouts)
2. Parallel makers with **git worktree** isolation when the job workspace is a git repo
3. **Commit milestone** gate before review
4. Diff-scoped **code review** then QA, with optional next wave

Root remains coordinator: children never `depends_on` the job root.

---

## Deliverables

- [x] `builtin_rails/greenfield-system.yml`
- [x] CE builtins: `plan_milestones`, `spawn_wave_makers`, `spawn_integrate`,
      `commit_milestone` (review prefers commit base)
- [x] Structural short-circuits for greenfield conditions
- [x] Catalog / README / unit tests
- [ ] Optional follow-up: DAG health deny child→root for rail jobs

---

## Operator usage

```bash
soothe autopilot submit "$(cat GOAL.md)" \
  --workspace /path/to/repo \
  --rail greenfield-system
```

---

## Out of scope

- Full automated `git merge` of worktrees inside the integrate builtin
- Changing global workspace-reservation defaults
- RailSelector auto-pick for greenfield (pass `--rail` explicitly)
