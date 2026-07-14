# IG-369: Langfuse AgentLoop and LangChain wiring fix

## Problem

- AgentLoop **Plan phase** (`LLMPlanner`) used `ainvoke` / structured output without LangChain `RunnableConfig` callbacks, so Langfuse saw **no** assess/plan generations even when `observability.langfuse.enabled` was true.
- Langfuse **Python SDK 3.x** targets Langfuse **platform ≥ 3.125**; the repo’s optional Docker stack used **`langfuse/langfuse:2`**, which is incompatible for reliable ingestion with SDK 3.
- Client init passed only `host`; SDK docs prefer **`base_url`** for self-hosted origins.

## Scope

1. **`merge_langfuse_runnable_config`**: optional `run_name` override; set Langfuse client `base_url` when host is configured.
2. **`langfuse_flush()`**: best-effort flush after CoreAgent streams so batches export promptly in long-running daemon.
3. **`LLMPlanner`**: pass merged Langfuse config into all plan-phase `ainvoke` calls when `SootheConfig` is present; use `thread_id` from `LoopState` / optional `PlanContext.thread_id`.
4. **`PlanContext`**: optional `thread_id` for pre-stream `create_plan` and Langfuse session correlation.
5. **`Executor`**: call `langfuse_flush` after successful sequential / single-step streams.
6. **`pyproject.toml`**: pin optional `soothe[langfuse]` to **`langfuse>=2.59.0,<3.0.0`** for compatibility with `langfuse/langfuse:2` in `docker-compose.yml`.
7. **`docker-compose.yml` / `config/config.dev.yml` / `IG-367`**: short compatibility note (SDK 2.x ↔ server 2).

## Verification

`./scripts/verify_finally.sh`
