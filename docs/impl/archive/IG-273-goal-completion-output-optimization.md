# IG-273 Goal Completion Output Optimization

## Context

Optimize goal completion output in TUI/CLI:

1. Rename final report concept to goal completion.
2. Return execute-phase assistant output directly when it already satisfies completion.
3. When synthesis is still needed, generate a dedicated goal completion message with IG-268 response length control.

## Implementation Scope

- AgentLoop completion orchestration and naming alignment.
- Runner event mapping for goal completion streaming.
- SDK output event registry compatibility.
- CLI/TUI output dedupe and completed-event payload compatibility.
- Unit tests for direct-return and synthesized goal completion paths.

## Change Plan

1. Add compatibility constants/fields for goal completion output events.
2. Refactor AgentLoop done-branch:
   - Evaluate direct-return branch first.
   - Trigger goal completion synthesis only when required.
3. Rename internal accumulator and message phase from final report to goal completion.
4. Update runner and client renderers to consume goal completion events.
5. Keep backward compatibility for existing final report names/fields.
6. Update docs/tests.

## Verification

- Targeted unit tests:
  - agent_loop adaptive final behavior
  - runner agentic final stdout behavior
  - CLI event processor behavior
  - CLI stream display pipeline behavior
- Run lints for touched files and fix introduced diagnostics.
