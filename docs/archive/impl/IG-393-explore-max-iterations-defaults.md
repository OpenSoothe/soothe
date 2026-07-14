# IG-393: Explore subagent — tighter default max model turns

**Status**: Completed  
**Purpose**: Align default `max_iterations` (LLM forward passes per Explore run) with LangChain `create_agent` behavior: parallel tool batches per turn make high caps mostly a cost/latency sink.

## Changes

1. **`ExploreSubagentConfig.max_iterations`** defaults: `quick` 12, `medium` 24, `thorough` 48 (was 30 / 50 / 100).
2. **`config.yml`** `subagents.explore.config.max_iterations` and inline comment.
3. **`config.dev.yml`** — add `subagents.explore` block mirroring template structure for local dev parity (CLAUDE.md).
4. **`build_explore_engine` fallback** when thoroughness key missing: use **24** (medium) instead of 50.

## Verification

`./scripts/verify_finally.sh`
