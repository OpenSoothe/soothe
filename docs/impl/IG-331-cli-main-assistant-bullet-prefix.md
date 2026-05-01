# IG-331: CLI main-agent AIMessage ● prefix

## Goal

Prefix headless CLI stdout for **main agent** assistant (`AIMessage`) text with `● ` so main replies align visually with stderr icon conventions.

## Behavior

- Non-empty chunks only receive the bullet once per assistant segment (streaming first chunk).
- After each finalized assistant flush (`is_streaming=False`), the next assistant segment gets a bullet again (multiple AIMessages per turn).
- Any stderr emission (progress, tools, errors) schedules a bullet before the next stdout assistant text.

## Verification

- `./scripts/verify_finally.sh`
