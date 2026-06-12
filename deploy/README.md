# Soothe Production Deployment Guide

This directory contains all essential files for production deployment of Soothe daemon with PostgreSQL + pgvector backend.

---

## Files in This Directory

### 1. Docker Compose (repo root)

Production stack is defined in `../docker-compose.yml` at the repository root. This directory supplies daemon config YAML, `.env`, and `init-db.sql` (also mirrored under `config/init-db.sql`).

Config files:
- `config.dev.yml` — local/Docker dev (default via `SOOTHE_CONFIG_PATH`)
- `config.prod.yml` — production deploy (`make docker-prod-up` sets this)

Services (with `--profile production`):
- `soothe-pgvector` - PostgreSQL 17 + pgvector extension
- `soothed` - Soothe daemon server
- Exposed on port 5432 (PostgreSQL) and 8765 (daemon) when `POSTGRES_PORT=5432` and `POSTGRES_BIND_IP=127.0.0.1` in `.env`
- **Critical**: `deploy/config.dev.yml` or `deploy/config.prod.yml` mounted at `/app/config.yml` in the container

### 2. .env.example
Environment variables template with:
- PostgreSQL credentials
- DashScope provider credentials
- Coding-Plan provider credentials
- Connection strings for RFC-612 multi-database architecture
- **NO OPENAI_API_KEY required** - custom providers use explicit config

**Usage**:
```bash
cp .env.example .env
vim .env  # Set your actual API keys and passwords
```

### 3. config.dev.yml / config.prod.yml
Agent configuration for Docker daemon (`soothed` service):
- `config.dev.yml` — dev defaults (Postgres at `soothe-pgvector:5432`, debug logging)
- `config.prod.yml` — production tuning

Select via `SOOTHE_CONFIG_PATH` in `.env` (default: `./deploy/config.dev.yml`).

### 4. init-db.sql
PostgreSQL initialization script (RFC-612 multi-database architecture):
- Creates 4 separate databases:
  - `soothe_checkpoints` - LangGraph + AgentLoop checkpoints
  - `soothe_metadata` - Durability metadata
  - `soothe_vectors` - pgvector embeddings (with vector extension)
  - `soothe_memory` - MemU long-term memory

**Usage**: Automatically executed on first PostgreSQL startup via docker-compose volume mount

---

## Deployment Steps

### Step 1: Prepare Configuration

```bash
cd soothe/deploy

# Create .env from example
cp .env.example .env
vim .env

# Set required values:
# - POSTGRES_PASSWORD=<secure_production_password>
# - DASHSCOPE_API_KEY=<your_dashscope_key>
# - DASHSCOPE_CP_API_KEY=<your_coding_plan_key>
# Note: NO OPENAI_API_KEY needed - custom providers work with explicit credentials
```

### Step 2: Choose daemon config

Dev (default):

```bash
# deploy/.env
SOOTHE_CONFIG_PATH=./deploy/config.dev.yml
```

Production:

```bash
# deploy/.env
SOOTHE_CONFIG_PATH=./deploy/config.prod.yml
```

### Step 3: Deploy Stack

```bash
# From repository root — dev Docker daemon
cd ..
docker compose --env-file deploy/.env --profile production up -d

# Or use Makefile targets:
#   make docker-daemon-up   # local image + config.dev.yml
#   make docker-prod-up     # registry image + config.prod.yml

# Verify services
docker compose --profile production ps

# Expected output:
# NAME                  STATUS        PORTS
# soothe-pgvector-1     Up (healthy)  127.0.0.1:5432->5432/tcp
# soothed-1             Up (healthy)  127.0.0.1:8765->8765/tcp
```

### Step 4: Verify Database Initialization

```bash
# Check PostgreSQL logs
docker compose logs soothe-pgvector | grep "CREATE DATABASE"

# Expected: 4 databases created
# - soothe_checkpoints
# - soothe_metadata
# - soothe_vectors (with pgvector extension)
# - soothe_memory

# Connect to verify
docker compose exec soothe-pgvector psql -U postgres -l
```

### Step 5: Verify Daemon Startup

The soothe daemon starts with the `production` profile:

```bash
# Check daemon status (from repo root)
docker compose --profile production ps

# Expected output:
# NAME                  STATUS        PORTS
# soothe-pgvector       Up (healthy)  127.0.0.1:5432->5432/tcp
# soothed               Up (healthy)  127.0.0.1:8765->8765/tcp

# Verify daemon listening
docker compose logs soothed | grep "listening on"
# Expected: "Unified channels listening on ws://0.0.0.0:8765"
```

**Note**: Daemon uses config from `/var/lib/soothe/config/config.yml` (mounted from ./config.yml)

---

## Architecture

### PostgreSQL Multi-Database (RFC-612)

```
PostgreSQL Instance (soothe-pgvector)
├── soothe_checkpoints    → LangGraph state persistence
├── soothe_metadata       → Thread metadata + durability
├── soothe_vectors        → Embeddings + vector search (pgvector)
└── soothe_memory         → Long-term memory storage
```

**Benefits**:
- Lifecycle isolation (separate backup/restore per database)
- Connection pool management per database
- pgvector extension only in vectors database
- Clear separation of concerns

### Network Configuration

```
Host Machine
└── Docker Container: soothe-pgvector
    └── Port 5432 (bind: 127.0.0.1)
    └── Internal networks: soothe-db, soothe-app

└── Docker Container: soothed
    └── Port 8765 (bind: 127.0.0.1)
    └── Config: /var/lib/soothe/config/config.yml (mounted)
```

**Security**:
- PostgreSQL bound to localhost (127.0.0.1:5432)
- Daemon bound to localhost (127.0.0.1:8765)
- Not exposed to public network
- Accessible only from same host or Docker networks

### Config Mount Path (Critical)

**Important**: Config file must be mounted at daemon's expected path:
```yaml
volumes:
  - ./config.yml:/var/lib/soothe/config/config.yml:ro  # ✅ Correct path
```

**Why**: Daemon loads config from `/var/lib/soothe/config/config.yml` by default.
- Wrong path: `/var/lib/soothe/config.yml` → empty config → default "openai:gpt-4o-mini" → OPENAI_API_KEY requirement
- Correct path: `/var/lib/soothe/config/config.yml` → loads DashScope/Coding-Plan → works without OPENAI_API_KEY

**Solution**: Mount at correct path so daemon loads providers successfully.

---

## Environment Variables Reference

### PostgreSQL Credentials
```bash
POSTGRES_USER=postgres                    # Database username
POSTGRES_PASSWORD=<secure_password>       # Database password (CHANGE IN PRODUCTION)
```

### DashScope Provider (Qwen, MiniMax, Kimi)
```bash
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=<your_key>              # DashScope API key
```

### Coding-Plan Provider (GLM, DeepSeek)
```bash
DASHSCOPE_CP_BASE_URL=https://coding.dashscope.aliyuncs.com/v1
DASHSCOPE_CP_API_KEY=<your_key>           # Coding-Plan API key
```

**Note**: NO OPENAI_API_KEY environment variable required - custom providers use explicit credentials from config.yml.

### PostgreSQL Connection Strings
```bash
SOOTHE_POSTGRES_BASE_DSN=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@soothe-pgvector:5432
SOOTHE_POSTGRES_VECTORS_DSN=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@soothe-pgvector:5432/soothe_vectors
```

---

## Configuration Reference

### config.yml Structure

```yaml
# Providers
providers:
  - name: dashscope
    provider_type: openai
    api_base_url: "${DASHSCOPE_BASE_URL}"     # Env var reference
    api_key: "${DASHSCOPE_API_KEY}"            # Env var reference
    models: [qwen-max, qwen3.5-flash, ...]

  - name: coding-plan
    provider_type: openai
    api_base_url: "${DASHSCOPE_CP_BASE_URL}"
    api_key: "${DASHSCOPE_CP_API_KEY}"
    models: [glm-5, qwen3.6-plus, ...]

# Router (model mapping)
router:
  default: "coding-plan:glm-5"          # Default model for queries
  fast: "coding-plan:kimi-k2.5"         # Fast model for quick responses
  think: "coding-plan:glm-5"            # Thinking model for complex tasks
  image: "coding-plan:qwen3.6-plus"     # Vision model for images
  embedding: "dashscope:multimodal-embedding-v1"  # Embedding model

# Persistence
persistence:
  default_backend: postgresql
  postgres_base_dsn: "${SOOTHE_POSTGRES_BASE_DSN}"  # Env var reference

# Vector Store (pgvector)
vector_stores:
  - name: pgvector
    provider_type: pgvector
    dsn: "${SOOTHE_POSTGRES_VECTORS_DSN}"          # Env var reference
    pool_size: 4
```

**Key Points**:
- All secrets referenced via `${ENV_VAR}` syntax
- Env vars resolved at runtime by soothe's `env.py`
- No hardcoded credentials in config file
- Multi-provider setup with custom OpenAI-compatible endpoints
- **propagate_env() fix deployed**: Custom providers skip OPENAI_API_KEY env var propagation

---

## Production Checklist

### Security
- ✅ Set strong POSTGRES_PASSWORD (not 'postgres')
- ✅ Store API keys securely (not in git)
- ✅ PostgreSQL bound to localhost (not public)
- ✅ Use Docker networks for service isolation

### Performance
- ✅ max_connections=200 (PostgreSQL connection pool)
- ✅ shm_size=256mb (shared memory for PostgreSQL)
- ✅ pool_size=4 (pgvector connection pool)
- ✅ Separate databases for different workloads
- ✅ propagate_env() fix deployed (no OPENAI_API_KEY pollution)

### Observability
- ✅ Health checks enabled (pg_isready)
- ✅ Logs accessible via `docker compose logs`
- ✅ Container restart policy: unless-stopped

### Backup
- ✅ Persistent volumes: soothe_postgres_data
- ✅ Database-level backup granularity (4 separate DBs)
- ✅ Volume namespaced: soothe_postgres_data (not generic)

---

## Troubleshooting

### Database Connection Issues

**Problem**: Cannot connect to PostgreSQL

**Solution**:
```bash
# Check PostgreSQL is running
docker compose ps soothe-pgvector

# Check logs
docker compose logs soothe-pgvector

# Verify credentials
docker compose exec soothe-pgvector psql -U postgres -c "SELECT 1"

# Check network connectivity
docker compose exec soothe-pgvector netstat -tlnp | grep 5432
```

### Database Initialization Issues

**Problem**: init-db.sql not executed

**Solution**:
```bash
# Check if script exists in container
docker compose exec soothe-pgvector ls -la /docker-entrypoint-initdb.d/

# Manual execution
docker compose exec soothe-pgvector psql -U postgres -f /docker-entrypoint-initdb.d/10-init-databases.sql

# Verify databases created
docker compose exec soothe-pgvector psql -U postgres -l
```

### pgvector Extension Issues

**Problem**: pgvector extension not installed

**Solution**:
```bash
# Connect to vectors database
docker compose exec soothe-pgvector psql -U postgres -d soothe_vectors

# Check extension
SELECT * FROM pg_extension WHERE extname = 'vector';

# Install manually if missing
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## Maintenance

### Backup PostgreSQL

```bash
# Backup all databases
docker compose exec soothe-pgvector pg_dumpall -U postgres > backup_all.sql

# Backup specific database
docker compose exec soothe-pgvector pg_dump -U postgres soothe_vectors > vectors_backup.sql

# Backup to volume
docker compose exec soothe-pgvector pg_dump -U postgres soothe_checkpoints > /var/lib/postgresql/data/checkpoints_backup.sql
```

### Restore PostgreSQL

```bash
# Restore all databases
cat backup_all.sql | docker compose exec -T soothe-pgvector psql -U postgres

# Restore specific database
cat vectors_backup.sql | docker compose exec -T soothe-pgvector psql -U postgres -d soothe_vectors
```

### Clean Restart

```bash
# Stop and remove containers + volumes
docker compose down -v

# Start fresh
docker compose up -d

# Warning: All data will be lost!
```

---

## Upgrading

### Upgrade PostgreSQL Image

```bash
# Pull new image
docker compose pull soothe-pgvector

# Restart with new image
docker compose up -d

# Verify version
docker compose exec soothe-pgvector psql -U postgres -c "SELECT version();"
```

### Upgrade init-db.sql

```bash
# Copy new script
cp soothe/config/init-db.sql deploy/init-db.sql

# Restart to execute (if fresh deployment)
docker compose down -v
docker compose up -d
```

---

## Integration with Soothe Daemon

This PostgreSQL stack is designed to work with the Soothe daemon running in a separate container or environment.

**Daemon Configuration** (in separate deployment):
```yaml
# In daemon's docker-compose.yml or environment
environment:
  SOOTHE_POSTGRES_BASE_DSN: postgresql://postgres:${POSTGRES_PASSWORD}@<this-pgvector-host>:5432
  SOOTHE_POSTGRES_VECTORS_DSN: postgresql://postgres:${POSTGRES_PASSWORD}@<this-pgvector-host>:5432/soothe_vectors

volumes:
  - ./config.yml:/var/lib/soothe/config.yml:ro  # Uses same config.yml
```

**Network Connection**:
- If daemon runs on same host: Use `localhost:5432` or `127.0.0.1:5432`
- If daemon runs in Docker: Use service name `soothe-pgvector:5432` with shared network
- If daemon runs remotely: Use host IP and ensure firewall allows port 5432

---

## File Manifest

```
soothe/deploy/
├── ../docker-compose.yml       # Unified stack (use --profile production from repo root)
├── .env.example                # Environment variables template
├── config.yml.example          # Agent configuration template
├── init-db.sql                 # PostgreSQL multi-database initialization
└── README.md                   # This deployment guide
```

---

## Quick Reference Commands

```bash
# Deploy
docker compose up -d

# Status
docker compose ps

# Logs
docker compose logs -f soothe-pgvector

# Connect to PostgreSQL
docker compose exec soothe-pgvector psql -U postgres

# List databases
docker compose exec soothe-pgvector psql -U postgres -l

# Check pgvector
docker compose exec soothe-pgvector psql -U postgres -d soothe_vectors -c "SELECT * FROM pg_extension WHERE extname='vector';"

# Stop
docker compose down

# Stop + remove volumes
docker compose down -v

# Restart
docker compose restart

# Update
docker compose pull && docker compose up -d
```

---

## Additional Resources

- **OPENAI_APIKEY_FIX_VERIFICATION.md** (in soothe repo) - Complete fix verification report
- **DEPLOYMENT_COMPLETE.md** (in deployment directory) - Production deployment success summary

---

## Support

For issues with this deployment:
1. Check logs: `docker compose logs soothe-pgvector`
2. Verify health: `docker compose ps`
3. Test connection: `docker compose exec soothe-pgvector psql -U postgres -c "SELECT 1"`
4. Review environment: `docker compose config`
5. Check volumes: `docker volume ls | grep soothe`

---

**Last Updated**: June 2, 2026
**Version**: Production v1.1
**Status**: Deployed successfully with propagate_env() fix