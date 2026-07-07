# IG-332: CLI tool call/result lines — flat display

## Goal

Headless CLI stderr tool rows should **not** use step-context tree branches (`└─`) or extra indentation; keep a single flat line:

`⚙ Glob(**/README*) -> ✓ Found 1 file`

## Implementation

- `CliRenderer.on_tool_call` / `on_tool_result`: drop `_is_inside_step_context` prefixes; remove unused helper.

## Verification

- `./scripts/verify_finally.sh`
