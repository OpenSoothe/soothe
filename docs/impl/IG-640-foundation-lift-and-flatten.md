# IG-640: Lift `soothe.foundation` → `soothe` and flatten modules

## Goal

Remove the `foundation` namespace wrapper and promote host libraries to
first-class top-level packages under `packages/soothe/src/soothe/`. Prefer
flat module files over nested packages except where a directory is justified
by size or a clear domain boundary.

Structural move only — **no behavior changes**.

## Target map

| From | To |
|------|-----|
| `soothe.foundation.coreagent` | `soothe.coreagent` |
| `soothe.foundation.sloop` | `soothe.sloop` |
| `soothe.foundation.autopilot` | `soothe.autopilot` |
| `soothe.foundation.context` | `soothe.context` |
| `soothe.foundation.persistence` | `soothe.persistence` |
| `soothe.foundation.events` | `soothe.events` |
| `soothe.foundation.identity` | `soothe.identity` |
| `soothe.foundation.cron` | `soothe.cron` |
| `soothe.foundation.workspace` | `soothe.workspace` |
| `soothe.foundation.ai_message` | `soothe.ai_message` |

No long-lived `soothe.foundation.*` compatibility shim. Hard cutover across
soothe, soothe-daemon, scripts, examples, docs, and tests.

## Flatten rules

Keep as packages: `sloop/engine`, `sloop/cognition`, `sloop/clarification`,
`sloop/intention`, `sloop/orchestrator` (without nested nodes), plus already-flat
`coreagent`, `events`, `identity`, `cron`, `workspace`.

Flatten / promote:

1. `sloop/nodes/*` → `sloop/nodes/*`
2. `sloop/checkpoints/*` → `sloop/checkpoints/*`
3. `sloop/` → flat files under `sloop/`
4. Keep `sloop/utils/` for loop-specific helpers; prefer `soothe.utils` when duplicated
5. `autopilot/{engine,monitor,service}/*` → single-level `autopilot/*.py`
6. `context/*` and `context/*` → flat `context/` modules
7. `persistence/db_init/` → `persistence/db_init.py`
8. Delete empty `sloop/prompts/`

Keep `persistence/sql/soothe_checkpoints/init.sql` (database-named
subdirectory is required by `load_init_script`).

Do **not** merge the three persistence domains (`soothe.persistence`,
`sloop.checkpoints`, context store).

## Non-goals

- Behavior, config schema, persistence backend semantics, or protocol changes
- Merging persistence domains into one package
- Renaming `sloop` / collapsing `runner`
- Publishing / version bump
- Long-lived deprecation shims

## Verification

- `./scripts/verify_finally.sh`
