# Soothe Production Deployment

Self-contained production stack: PostgreSQL + pgvector + Soothe daemon.

## Quick Start

```bash
cd deploy
cp env-example .env && vim .env   # Set API keys
mkdir -p "$HOME/.soothe/data" "$HOME/.soothe/logs"  # required before first up
docker compose up -d
```

Or from the repo root: `make docker-prod-up` (creates those dirs automatically).

Verify: `docker compose ps` — should show soothe-pgvector and soothed running.

**Colima note**: If you see `chown .../.soothe/logs: permission denied` when starting, the host bind-mount dirs were missing and Docker tried to create+chown them on sshfs (unsupported). Create the dirs on the host and retry.

## Environment Variables

Required (`.env`):
- `OPENAI_API_KEY` — OpenAI-compatible provider key

Optional:
- `SOOTHE_WORKSPACE_HOST_ROOT` — Host workspace path (default: `$HOME` via docker-compose)

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

`nano.yml` uses OpenAI-Custom/Coding-Plan providers with `${ENV_VAR}` substitution.

## Security

- ✅ API keys in `.env` (not git)
- ✅ Localhost binding only
- ✅ Docker network isolation