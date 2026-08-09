# IG-734: Collapse redundant builtin rails (hard cut)

## Goal

Remove topology-duplicate builtins `bugfix` and `migration`. Absorb their
gates into `feature-dev` and `greenfield-system`. No aliases.

## Status

Done.

## Scope

- [x] Merge defect gates into `feature-dev` (`ready_to_fix` + broadened prose)
- [x] Merge cutover pause + migration planner copy into `greenfield-system`
- [x] Delete `bugfix.yml` / `migration.yml`
- [x] Update catalog tests, README, migration→greenfield unit coverage
- [x] Verify (`./scripts/verify_finally.sh`)

## Breaking

`--rail bugfix` / `--rail migration` and in-flight jobs with those `rail_id`s
fail catalog resolve. Resubmit with `feature-dev` or `greenfield-system`.

## Out of scope

- Historical job row rewrites
- Changes to hotfix / maker-checker / spike / pr-review
