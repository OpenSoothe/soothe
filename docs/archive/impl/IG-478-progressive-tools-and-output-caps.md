# IG-478: Progressive Tools and Model Output Caps

## Goal

Reduce Langfuse `model` span latency (pre-HTTP `bind_tools` gap + oversized prompts) for execute steps.

## Changes

- P0-1: `code_exec_max_output_chars` / `tool_output_max_chars` config; `ToolOutputCapMiddleware`
- P0-2: `progressive_tools` config; core-tier binding; `<AVAILABLE_TOOLS>` listing; `search_tools`
- P1: `workspace_instructions_max_chars`; simple-tier WORKSPACE_INSTRUCTIONS deferral; profiler block breakdown

## Files

- `packages/soothe/src/soothe/middleware/tool_output_cap.py`
- `packages/soothe/src/soothe/middleware/progressive_tools.py`
- `packages/soothe/src/soothe/toolkits/progressive/`
- `config/config.template.yml`, `config/develop/config.yml`

## Status

Completed.
