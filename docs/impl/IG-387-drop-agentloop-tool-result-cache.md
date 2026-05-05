# IG-387: Drop AgentLoop ToolResultCache

**Status**: Completed  
**Scope**: Remove `ToolResultCache` from the AgentLoop executor and delete the unused config surface (`ToolResultCacheConfig` / `execution.tool_result_cache`). Large tool outputs continue to be handled by deepagents `FilesystemMiddleware` eviction where applicable; CoreAgent/LangGraph retains full `ToolMessage` content in checkpoints when not evicted.

**Rationale**: The cache duplicated spill-like behavior without a consumer (`ToolResultCache.load` was never called). Removing it avoids extra JSON writes under `data/threads/.../tool_results/` and simplifies the act-stream path.

**Files**:
- `packages/soothe/src/soothe/core/agent_loop/core/executor.py` — stop importing/using cache
- `packages/soothe/src/soothe/core/agent_loop/context/result_cache.py` — delete
- `packages/soothe/src/soothe/core/agent_loop/context/__init__.py` — drop export
- `packages/soothe/src/soothe/config/models.py` — remove `ToolResultCacheConfig` and field on `ExecutionConfig`
- `packages/soothe/src/soothe/config/__init__.py` — drop re-exports
- `packages/soothe/src/soothe/core/agent_loop/analysis/metadata_generator.py` — docstring only (`file_ref` no longer set here)

**Verification**: `./scripts/verify_finally.sh`
