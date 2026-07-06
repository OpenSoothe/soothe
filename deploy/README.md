# Soothe Production Deployment

Self-contained production stack: PostgreSQL + pgvector + Soothe daemon.

## Quick Start

```bash
cd deploy
cp .env.example .env && vim .env   # Set API keys and workspace path
docker compose up -d
```

Verify: `docker compose ps` — should show soothe-pgvector and soothed running.

## Environment Variables

Required (`.env`):
- `DASHSCOPE_API_KEY` — DashScope provider key
- `SOOTHE_WORKSPACE_HOST_ROOT` — Host workspace path

## Architecture

```
soothe-pgvector (PostgreSQL 17 + pgvector)
├── soothe_checkpoints   → LangGraph state (auto-provisioned on daemon start)
├── soothe_metadata      → Thread metadata
├── soothe_vectors       → Embeddings (+ pgvector extension)
└── soothe_memory        → Long-term memory

soothed (daemon)
└── Port 8765 (WebSocket/HTTP API)
```

All services bound to localhost only. PostgreSQL uses default credentials (postgres/postgres).

## Operations

| Action | Command |
|--------|---------|
| Status | `docker compose ps` |
| Logs | `docker compose logs soothed` |
| Connect DB | `docker compose exec soothe-pgvector psql -U postgres` |
| Backup | `docker compose exec soothe-pgvector pg_dumpall -U postgres > backup.sql` |
| Stop | `docker compose down` |
| Clean restart | `docker compose down -v && docker compose up -d` |

## Config

`config.prod.yml` uses DashScope/Coding-Plan providers with `${ENV_VAR}` substitution.

## Security

- ✅ API keys in `.env` (not git)
- ✅ Localhost binding only
- ✅ Docker network isolation