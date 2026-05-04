# IG-375: Remove LangSmith tracing

## Goal

Remove first-party LangSmith integration: env propagation, project override, TUI `/trace`, doctor observability check, startup status logging, and LangSmith-specific stream metadata.

## Scope

- `packages/soothe-cli`: bootstrap, `Settings` fields, `/trace`, `build_stream_config` `ls_integration`
- `packages/soothe`: `observability_check`, `logging/setup.py` LangSmith status

## Out of scope

- LangChain may still honor user-set `LANGCHAIN_TRACING_V2` / vendor env vars; Soothe no longer documents or bridges them.
- `observability.llm_tracing_*` (local log middleware) unchanged.

## Status

- [x] Implementation
- [x] `./scripts/verify_finally.sh`
