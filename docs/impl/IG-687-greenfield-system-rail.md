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
5. **Feedback cycle** (`spawn_feedback_cycle`): find → optimize → verify until
   acceptance (or `max_feedback_rounds`)

Root remains coordinator: children never `depends_on` the job root; rail-bound
job roots are not dispatched as workers.

---

## Deliverables

- [x] `builtin_rails/greenfield-system.yml`
- [x] CE builtins: `plan_milestones`, `spawn_wave_makers`, `spawn_integrate`,
      `commit_milestone` (review prefers commit base)
- [x] CE builtin: `spawn_feedback_cycle` (diagnose / optimize / verify)
- [x] Structural short-circuits for greenfield conditions (incl. `needs_feedback`,
      commit-gated `needs_review`)
- [x] DAG health deny child→root for rail jobs
- [x] Catalog / README / unit tests

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
