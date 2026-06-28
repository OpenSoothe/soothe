# Production Setup Guide

Complete guide for deploying Soothe in production environments.

## Overview

This guide covers production deployment using Docker Compose (recommended), systemd for bare metal deployments, and Kubernetes for large-scale environments.

## Prerequisites

### System Requirements

**Minimum** (10 users, <50 threads):
- CPU: 2 cores
- RAM: 4 GB
- Storage: 20 GB SSD
- Network: Stable LAN connection

**Recommended** (50 users, <200 threads):
- CPU: 4 cores
- RAM: 8 GB
- Storage: 50 GB SSD
- Network: Dedicated database connection

**Large Scale** (500 users, >200 threads):
- See [Scaling Strategies](scaling.md)

### Software Requirements

- Docker 24.0+ and Docker Compose 2.20+
- PostgreSQL 17+ (or use Docker image)
- Python 3.11+ (for systemd deployment)

### Network Requirements

- Database port (5432) accessible from daemon
- Daemon port (8765) accessible from clients (if WebSocket enabled)
- Outbound HTTPS for LLM provider APIs

## Docker Compose Deployment (Recommended)

The fastest way to deploy Soothe in production.

### Step 1: Prepare Configuration Files

```bash
# Navigate to deployment directory
cd soothe/deploy

# Create environment file
cp .env.example .env
vim .env
```

**Required environment variables**:
```bash
# PostgreSQL credentials
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<secure_password>  # Generate with: openssl rand -base64 32

# LLM provider credentials
DASHSCOPE_API_KEY=<your_dashscope_key>
DASHSCOPE_CP_API_KEY=<your_coding_plan_key>

# Optional: OpenAI
OPENAI_API_KEY=<your_openai_key>  # Only if using OpenAI models

# Connection strings (auto-generated)
SOOTHE_POSTGRES_BASE_DSN=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@soothe-pgvector:5432
SOOTHE_POSTGRES_VECTORS_DSN=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@soothe-pgvector:5432/soothe_vectors
```

**Security**: Never commit `.env` to version control. Use secrets management for production.

### Step 2: Create Agent Configuration

```bash
cp config.yml.example config.yml
vim config.yml  # Optional customization
```

**Default configuration** (uses environment variables):
```yaml
providers:
  - name: dashscope
    provider_type: openai
    api_base_url: "${DASHSCOPE_BASE_URL}"
    api_key: "${DASHSCOPE_API_KEY}"
    models:
      - qwen-max
      - qwen3.7-plus
      - multimodal-embedding-v1

router:
  default: "dashscope:qwen-max"
  embedding: "dashscope:multimodal-embedding-v1"

persistence:
  default_backend: postgresql
  postgres_base_dsn: "${SOOTHE_POSTGRES_BASE_DSN}"

vector_stores:
  - name: pgvector
    provider_type: pgvector
    dsn: "${SOOTHE_POSTGRES_VECTORS_DSN}"
    pool_size: 4

vector_store_router:
  default: "pgvector:soothe_default"
```

**Key points**:
- Environment variables referenced with `${ENV_VAR}`
- PostgreSQL backend for production durability
- pgvector for vector similarity search

### Step 3: Deploy Stack

```bash
# Start services
docker compose up -d

# Verify deployment
docker compose ps

# Expected output:
# NAME                  STATUS        PORTS
# soothe-pgvector-1     Up (healthy)  127.0.0.1:5432->5432/tcp
# soothed-1             Up (healthy)  127.0.0.1:8765->8765/tcp
```

### Step 4: Verify Database Initialization

```bash
# Check PostgreSQL logs for initialization
docker compose logs soothe-pgvector | grep "init-databases"

# Verify databases created
docker compose exec soothe-pgvector psql -U postgres -l

# Expected databases:
# soothe_checkpoints | postgres | UTF8
# soothe_metadata    | postgres | UTF8
# soothe_vectors     | postgres | UTF8 | pgvector extension
# soothe_memory      | postgres | UTF8
```

**RFC-802 Multi-database architecture**:
- `soothe_checkpoints`: LangGraph + StrangeLoop state
- `soothe_metadata`: Thread lifecycle metadata
- `soothe_vectors`: Embedding vectors (pgvector)
- `soothe_memory`: Long-term semantic memory

### Step 5: Verify Daemon Health

```bash
# Check daemon logs
docker compose logs soothed

# Test daemon connectivity (WebSocket)
soothe --daemon-host 127.0.0.1 --daemon-port 8765 -p "Hello"  # Test WebSocket connectivity
```

### Step 6: Test Full Stack

```bash
# Send test query
soothe -p "List all Python files in the workspace"  # CLI auto-connects to daemon

# Verify thread created in database
docker compose exec soothe-pgvector psql -U postgres -d soothe_metadata \
  -c "SELECT thread_id, status FROM threads LIMIT 5"
```

### Production Docker Compose Configuration

**Key settings in `deploy/docker-compose.yml`**:

```yaml
services:
  soothe-pgvector:
    image: registry.cn-hangzhou.aliyuncs.com/lacogito/pgvector:pg17
    restart: unless-stopped
    command: ["postgres", "-c", "max_connections=200"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 20s
    shm_size: 256mb
    volumes:
      - soothe_postgres_data:/var/lib/postgresql/data
      - ./init-db.sql:/docker-entrypoint-initdb.d/10-init-databases.sql:ro

  soothed:
    image: registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
    restart: unless-stopped
    depends_on:
      soothe-pgvector:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import socket; ...'"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    volumes:
      - soothe_daemon_data:/var/lib/soothe
      - ./config.yml:/var/lib/soothe/config/config.yml:ro
      # Workspace mount (RFC-621)
      - /path/to/workspace:/var/lib/soothe/workspaces
```

**Production considerations**:
- `restart: unless-stopped`: Auto-restart on failure
- Health checks: Container health monitoring
- Volume mounts: Persistent data storage
- Config mount: Read-only configuration
- Workspace mount: Client workspace access (RFC-621)

### Persistent Volumes

```yaml
volumes:
  soothe_postgres_data:
    name: soothe_postgres_data
  soothe_daemon_data:
    name: soothe_daemon_data
```

**Backup strategy**:
```bash
# Backup PostgreSQL data
docker run --rm -v soothe_postgres_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres_backup_$(date +%Y%m%d).tar.gz /data

# Backup daemon data
docker run --rm -v soothe_daemon_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/daemon_backup_$(date +%Y%m%d).tar.gz /data
```

See [Backup Recovery](backup-recovery.md) for comprehensive backup strategies.

## systemd Deployment (Bare Metal)

For environments without Docker or requiring direct hardware access.

### Step 1: Install Dependencies

```bash
# Install PostgreSQL
sudo apt install postgresql-17 postgresql-17-pgvector

# Install Python 3.11+
sudo apt install python3.11 python3.11-venv python3-pip

# Create PostgreSQL databases
sudo -u postgres psql -f deploy/init-db.sql
```

### Step 2: Configure PostgreSQL

```bash
# Edit PostgreSQL configuration
sudo vim /etc/postgresql/17/main/postgresql.conf

# Recommended settings:
max_connections = 200
shared_buffers = 256MB
work_mem = 16MB
```

```bash
# Enable pgvector extension
sudo -u postgres psql -d soothe_vectors -c "CREATE EXTENSION vector;"
```

### Step 3: Create Soothe User

```bash
# Create dedicated user
sudo useradd -r -s /bin/false soothe

# Create directories
sudo mkdir -p /var/lib/soothe /var/log/soothe
sudo chown soothe:soothe /var/lib/soothe /var/log/soothe
```

### Step 4: Install Soothe Package

```bash
# Create virtual environment
sudo python3.11 -m venv /opt/soothe/venv

# Install package
sudo /opt/soothe/venv/bin/pip install soothe-daemon soothe

# Or install from source
sudo /opt/soothe/venv/bin/pip install -e /path/to/soothe/packages/soothe
```

### Step 5: Configure Soothe

```bash
# Create configuration
sudo mkdir -p /var/lib/soothe/config
sudo cp deploy/config.yml.example /var/lib/soothe/config/config.yml
sudo vim /var/lib/soothe/config/config.yml

# Set environment variables
sudo vim /etc/default/soothe
```

**`/etc/default/soothe`**:
```bash
SOOTHE_POSTGRES_BASE_DSN=postgresql://postgres:password@localhost:5432
DASHSCOPE_API_KEY=<your_key>
SOOTHE_LOG_FILE_PATH=/var/log/soothe/soothed.log
SOOTHE_LOG_FILE_LEVEL=INFO
```

### Step 6: Create systemd Service

**`/etc/systemd/system/soothed.service`**:
```ini
[Unit]
Description=Soothe Daemon - Autonomous Agent Orchestration Server
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=soothe
Group=soothe
EnvironmentFile=/etc/default/soothe
ExecStart=/opt/soothe/venv/bin/soothed start --foreground
ExecStop=/opt/soothe/venv/bin/soothed stop
Restart=on-failure
RestartSec=5s

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/soothe /var/log/soothe

# Resource limits
LimitNOFILE=65536
MemoryMax=4G

[Install]
WantedBy=multi-user.target
```

### Step 7: Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (auto-start on boot)
sudo systemctl enable soothed

# Start service
sudo systemctl start soothed

# Check status
sudo systemctl status soothed

# View logs
sudo journalctl -u soothed -f
```

### systemd Best Practices

**Resource limits**:
```ini
# Memory limit (prevent OOM)
MemoryMax=4G

# CPU limit (if multiple services)
CPUQuota=50%

# File descriptor limit (for many connections)
LimitNOFILE=65536
```

**Security hardening**:
```ini
# Prevent privilege escalation
NoNewPrivileges=true

# Isolate filesystem
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

# Allow only specific paths
ReadWritePaths=/var/lib/soothe /var/log/soothe
```

**Restart behavior**:
```ini
# Restart on failure
Restart=on-failure
RestartSec=5s

# Or always restart (more aggressive)
Restart=always
RestartSec=10s
```

## Kubernetes Deployment

For large-scale, high-availability deployments.

See [Scaling Strategies](scaling.md) for complete Kubernetes deployment guide including:
- StatefulSet for PostgreSQL
- Deployment for Soothe daemon
- Service and Ingress configuration
- Horizontal Pod Autoscaler
- ConfigMap and Secrets management

## Network Configuration

### Database Connection

**PostgreSQL DSN format**:
```
postgresql://user:password@host:port/database
```

**Example**:
```yaml
persistence:
  postgres_base_dsn: postgresql://postgres:secret@postgres-host:5432
```

**Production recommendations**:
- Use TLS for database connections (`sslmode=require`)
- Use connection pooling (psycopg pool)
- Set reasonable timeouts (`connect_timeout=10`)
- Use read replicas for query-heavy loads

**Example with TLS**:
```yaml
persistence:
  postgres_base_dsn: postgresql://user:pass@host:5432?sslmode=require&connect_timeout=10
```

### Daemon Transports

Configure in `~/.soothe/config/daemon.yml`:

**WebSocket (local and remote)**:
```yaml
transports:
  websocket:
    enabled: true
    host: "127.0.0.1"  # Bind to localhost; use reverse proxy for remote
    port: 8765
    cors_origins: ["https://your-app.com"]
```

**Important**: Use reverse proxy for remote WebSocket access. See [Security Hardening](security.md).

### Firewall Rules

**Production firewall configuration**:

```bash
# Allow PostgreSQL from daemon only (Docker internal network)
# No external PostgreSQL access needed

# Allow daemon WebSocket from reverse proxy
sudo ufw allow from 10.0.0.0/8 to any port 8765 proto tcp

# Block direct daemon access from external
sudo ufw deny 8765

# Allow reverse proxy HTTPS
sudo ufw allow 443/tcp
```

## Workspace Mount Configuration (RFC-621)

For container deployments, workspace paths need mapping between host and container.

### Docker Compose Workspace Mount

```yaml
services:
  soothed:
    volumes:
      # Host workspace → container workspace
      - /Users/yourname/Workspace:/var/lib/soothe/workspaces
```

### Configuration Mapping

```yaml
workspace_mount:
  host_root: /Users/yourname/Workspace
  container_root: /var/lib/soothe/workspaces
```

**How it works**:
- Client sends workspace path: `/Users/yourname/Workspace/project1`
- Daemon maps to container path: `/var/lib/soothe/workspaces/project1`
- File operations work correctly in container

### Production Workspace Strategies

**Strategy 1: Shared workspace mount**:
```yaml
# Mount entire workspace directory
- /home/team/workspace:/var/lib/soothe/workspaces
```

**Strategy 2: Per-project mounts**:
```yaml
# Mount specific projects
- /var/www/project-a:/var/lib/soothe/workspaces/project-a
- /var/www/project-b:/var/lib/soothe/workspaces/project-b
```

**Strategy 3: Dynamic mounts** (Kubernetes):
- Use PersistentVolumeClaims
- Mount PVCs to daemon pods
- See [Scaling Strategies](scaling.md)

## Verification Checklist

After deployment, verify:

### Database Connectivity

```bash
# Test PostgreSQL connection
psql -h postgres-host -U user -d soothe_checkpoints -c "SELECT 1"

# Verify pgvector extension
psql -h postgres-host -U user -d soothe_vectors -c "SELECT * FROM pg_extension WHERE extname='vector'"

# Check databases exist
psql -h postgres-host -U user -l | grep soothe
```

### Daemon Health

```bash
# Check daemon status
soothed status

# Verify transports
soothed status --verbose

# Test WebSocket
curl http://localhost:8765/health
```

### Configuration

```bash
# Verify environment variables
docker compose exec soothed env | grep SOOTHE

# Check config loaded
docker compose logs soothed | grep "config loaded"
```

### Thread Creation

```bash
# Create test thread
soothe -p "Hello, this is a test"  # CLI auto-connects to daemon

# Verify in database
psql -h postgres-host -U user -d soothe_metadata \
  -c "SELECT thread_id, created_at FROM threads ORDER BY created_at DESC LIMIT 1"
```

## Troubleshooting Production Deployment

### PostgreSQL Connection Issues

**Error**: `Connection refused` or `could not connect to server`

**Solution**:
1. Check PostgreSQL is running: `docker compose ps soothe-pgvector`
2. Verify network: `docker compose exec soothe-pgvector ping soothe-pgvector`
3. Check credentials in `.env`
4. Verify firewall rules

### pgvector Extension Missing

**Error**: `extension "vector" must be installed`

**Solution**:
```bash
# Install extension manually
docker compose exec soothe-pgvector psql -U postgres -d soothe_vectors \
  -c "CREATE EXTENSION vector;"

# Verify extension
docker compose exec soothe-pgvector psql -U postgres -d soothe_vectors \
  -c "SELECT * FROM pg_extension WHERE extname='vector'"
```

### Daemon Won't Start

**Error**: `Daemon startup failed`

**Solution**:
1. Check logs: `docker compose logs soothed`
2. Verify config.yml syntax: `python -c "import yaml; yaml.safe_load(open('config.yml'))"`
3. Check environment variables: `docker compose config`
4. Verify workspace mount exists

### Workspace Access Denied

**Error**: `Permission denied` when accessing workspace

**Solution**:
```bash
# Check mount permissions
docker compose exec soothed ls -la /var/lib/soothe/workspaces

# Fix permissions on host
chmod -R a+rx /path/to/workspace

# Or use proper user mapping in Docker Compose
user: "1000:1000"  # Match host user UID:GID
```

## Production Configuration Examples

### Example 1: Standard Production (DashScope + PostgreSQL)

```yaml
providers:
  - name: dashscope
    provider_type: openai
    api_base_url: "${DASHSCOPE_BASE_URL}"
    api_key: "${DASHSCOPE_API_KEY}"
    models:
      - qwen-max
      - qwen3.7-plus
      - multimodal-embedding-v1

router:
  default: "dashscope:qwen-max"
  fast: "dashscope:qwen3.7-plus"
  think: "dashscope:qwen-max"
  embedding: "dashscope:multimodal-embedding-v1"

persistence:
  default_backend: postgresql
  postgres_base_dsn: "${SOOTHE_POSTGRES_BASE_DSN}"
  postgres_pool_min_size: 8
  checkpointer_pool_size: 24

vector_stores:
  - name: pgvector
    provider_type: pgvector
    dsn: "${SOOTHE_POSTGRES_VECTORS_DSN}"
    pool_size: 8
    index_type: hnsw

observability:
  log_file_path: /var/log/soothe/soothed.log
  log_file_level: INFO
  verbosity: normal
```

### Example 2: Multi-Provider Production (OpenAI + Anthropic + PostgreSQL)

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"
    models:
      - gpt-4o
      - gpt-4o-mini
      - o3-mini

  - name: anthropic
    provider_type: anthropic
    api_key: "${ANTHROPIC_API_KEY}"
    models:
      - claude-sonnet-4-20250514

router:
  default: "openai:gpt-4o-mini"
  think: "anthropic:claude-sonnet-4-20250514"
  fast: "openai:gpt-4o-mini"
  image: "openai:gpt-4o"
  embedding: "openai:text-embedding-3-small"

persistence:
  default_backend: postgresql
  postgres_base_dsn: "${POSTGRES_DSN}"
```

### Example 3: Secure Production (Strict Security Policy)

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"
    models:
      - gpt-4o-mini

persistence:
  default_backend: postgresql

security:
  sandbox: false
  allow_paths_outside_workspace: false
  require_approval_for_outside_paths: true
  denied_paths:
    - /etc/**
    - /bin/**
    - /usr/**
    - ~/.ssh/**
    - ~/.aws/**
    - '**/.env'
    - '**/secrets.json'
  denied_file_types:
    - .key
    - .pem
    - .p12
  require_approval_for_file_types:
    - .env
    - .credentials

agent:
  autonomous:
    enabled_by_default: false
    max_iterations: 15
    max_parallel_goals: 2
```

## Next Steps

After successful production deployment:

1. **Monitoring**: Configure observability → [Monitoring Guide](monitoring.md)
2. **Security**: Harden deployment → [Security Hardening](security.md)
3. **Scaling**: Plan for growth → [Scaling Strategies](scaling.md)
4. **Backup**: Protect data → [Backup Recovery](backup-recovery.md)

## Related Documentation

- [Deployment Guide Overview](README.md) - Deployment architecture overview
- [Docker Compose Reference](../../deploy/docker-compose.yml) - Production stack definition
- [Configuration Guide](../configuration-guide/README.md) - Complete YAML reference
- [Daemon Management](../daemon-management.md) - Daemon lifecycle commands
- [Multi-Transport](../multi-transport.md) - Transport configuration
- [Authentication](../authentication.md) - Reverse proxy authentication

---

**Questions?** Check [Troubleshooting](../troubleshooting.md) or the [Production Deployment README](../../deploy/README.md).