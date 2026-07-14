# IG-326: Explore `search_target` from task message

## Problem

The explore LangGraph reads `search_target` only from graph state. The `task` tool passes the user request in `messages` as a `HumanMessage` but never sets `search_target`, so planning prompts had an empty `Target:` and assess/synthesize lacked the real goal.

## Change

- Add `resolve_explore_search_target()` to derive the target from explicit state or the latest `HumanMessage` text (including multimodal text blocks).
- Use it in `plan_search`, `assess_results`, and `synthesize`; persist `search_target` into state from `plan_search` when it was missing.
- Harden fallback glob when there is no first token.
- After assess, route `continue` (and `adjust`) to `plan_search`, not `execute_action`: once tools have run, `messages[-1]` is a `ToolMessage`, so re-entering `execute_action` no-ops in a loop.
- `execute_action` must not assume `messages[-1]` is the planner: resolve the newest `AIMessage` with tool calls that still lacks matching `ToolMessage` replies, and invoke `ToolNode` on the prefix through that message (avoids stale-tail and duplicate older-AI execution).

## Verification

- `./scripts/verify_finally.sh`
