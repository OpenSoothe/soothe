# IG-117: System Prompt Shared Prefix (RFC-104 alignment)

**Status**: Completed  
**Scope**: Shared nested XML builders for dynamic system context, planner/reason prompt alignment, prompt-cache-friendly ordering.

## Summary

- Added `src/soothe/core/prompts/context_xml.py` with `build_soothe_*_section` helpers, `build_shared_environment_workspace_prefix`, and `build_context_sections_for_complexity`.
- `SystemPromptOptimizationMiddleware` delegates to `context_xml`; static behavioral prompt precedes volatile XML blocks; current date line is appended last.
- `PlanContext` and `LoopState` carry optional `git_status`; runner planning paths and agentic loop pass it through.
- `SimplePlanner` / `ClaudePlanner` receive `SootheConfig` from `resolve_planner` and prepend the same ENV+WORKSPACE prefix (planning uses optional layout/README caps).
- `build_loop_reason_prompt` prepends shared blocks when `config` is set; legacy no-config path keeps workspace-only XML.
- Normative tag shape and cache ordering: `docs/specs/RFC-104-dynamic-system-context.md`.

## Verification

Run `./scripts/verify_finally.sh` before merge.
