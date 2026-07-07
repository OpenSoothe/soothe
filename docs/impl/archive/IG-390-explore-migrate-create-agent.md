# IG-390: Explore subagent — migrate to LangChain `create_agent`

**Status**: Completed  
**Scope**: Replace hand-rolled `StateGraph` (plan → tools → assess → branch) with `langchain.agents.create_agent` + middleware. Public export `ExploreState` → `ExploreAgentState` (no backward compatibility).

## Design

- **Graph**: `create_agent(model, tools, system_prompt, middleware, response_format=ExploreResult, state_schema=ExploreAgentState)`.
- **Async**: Middleware implements `awrap_model_call`, `awrap_tool_call`, and delegates `abefore_agent` / `aafter_model` / `aafter_agent` so parent `task` tool `ainvoke` works (LangChain raises if only sync hooks exist).
- **Messages**: Standard LangChain agent loop; `after_agent` overwrites `messages` with a single markdown `AIMessage` for the parent `task` tool.
- **Findings**: `findings` field with `operator.add` reducer; `ExploreFindingsMiddleware.wrap_tool_call` appends rows from `glob`/`grep`/`ls`/`read_file`/`file_info`.
- **Budget**: `ExplorePromptBudgetMiddleware.wrap_model_call` counts `explore_model_invocations`; at cap, forces `model.with_structured_output(ExploreResult)` with `SYNTHESIZE` prompt.
- **Wire events**: `ExploreWireMiddleware` (started), `ExplorePromptBudgetMiddleware` (milestone on fs tool plan), `ExploreFinalizeMiddleware` (completed).

## Files

| Path |
|------|
| `packages/soothe/src/soothe/subagents/explore/engine.py` |
| `packages/soothe/src/soothe/subagents/explore/middleware.py` |
| `packages/soothe/src/soothe/subagents/explore/findings.py` |
| `packages/soothe/src/soothe/subagents/explore/schemas.py` |
| `packages/soothe/src/soothe/subagents/explore/prompts.py` |
| `packages/soothe/src/soothe/subagents/explore/__init__.py` |
| `packages/soothe/tests/unit/subagents/explore/test_create_agent_engine.py` |

## Removed

- `route_after_explore_assessment`, `pending_tool_ai_index_and_message`, `recent_messages_for_explore_plan` from `engine.py`
- Unit tests tied to the old graph (`test_plan_search_recent_messages`, `test_assessment_routing`, `test_pending_tool_ai`)

## Verification

```bash
./scripts/verify_finally.sh
```
