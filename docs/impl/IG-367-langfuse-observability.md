# IG-367: Langfuse observability integration

## Goal

Integrate Langfuse tracing for LangChain / LangGraph runs driven by `observability.langfuse` in Soothe config, and surface configuration in health checks.

## Scope

- Pydantic models under `observability.langfuse` (enabled, keys, host, environment, release, sample_rate, trace_name).
- Runtime helper to register the Langfuse SDK client (when keys are set in config) and merge `CallbackHandler` + session metadata into Runnable configs.
- Wire into `SootheRunner` stream phase, `AgentLoop` executor streams, and goal-completion synthesis stream.
- Optional dependency `soothe[langfuse]`; template `config.yml` + `config/config.dev.yml` documentation.
- Doctor observability category: Langfuse check when integration is enabled.

## Local Langfuse (Docker)

From repo root:

```bash
docker compose up -d
```

- UI / API base URL: `http://localhost:3300` (host port **3300** → Langfuse web **3000**).
- Default dev API keys (overridable via `LANGFUSE_INIT_PROJECT_*` env): `pk-lf-soothe-local` / `sk-lf-soothe-local`.
- Headless UI user (compose defaults): `dev@soothe.local` / `SootheLangfuseLocalDev1` — override with `LANGFUSE_INIT_USER_*` before first boot.
- Enable tracing in Soothe via `observability.langfuse` in `config/config.dev.yml` (or your chosen YAML).
- Langfuse services are part of the default `docker compose` stack (same file as `soothe-pgvector`); omit or scale them to zero if you only need the database.

## Verification

Run `./scripts/verify_finally.sh` before merge.
