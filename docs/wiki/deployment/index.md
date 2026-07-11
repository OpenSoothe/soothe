---
title: Deployment
parent: Wiki
has_children: true
nav_order: 9
description: >-
  Production setup, monitoring, security, scaling, and backup recovery.
permalink: /wiki/deployment/
---

# Deployment Guide

Comprehensive deployment documentation for production, development, and scaling Soothe.

## Overview

This guide covers production deployment patterns, monitoring setup, security hardening, scaling strategies, and disaster recovery. For basic daemon management, see [Daemon Management](../daemon-management.md).

## Quick Reference

| Topic | Guide | Key Focus |
|-------|-------|-----------|
| Production Setup | [Production Setup](production-setup.md) | Docker Compose, PostgreSQL, pgvector |
| Monitoring | [Monitoring Guide](monitoring.md) | Langfuse, logs, health checks |
| Security | [Security Hardening](security.md) | Reverse proxy, TLS, access control |
| Scaling | [Scaling Strategies](scaling.md) | Horizontal scaling, load balancing |
| Backup & Recovery | [Backup Recovery](backup-recovery.md) | PostgreSQL backup, disaster recovery |

## Deployment Architecture

Soothe supports three deployment tiers:

### Tier 1: Local Development

```
┌─────────────┐
│ CLI/TUI     │
│ (WebSocket) │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Soothe     │
│  Daemon     │
│ (SQLite)    │
└─────────────┘
```

**Best for**: Development, testing, single-user environments

**Configuration**:
```yaml
persistence:
  default_backend: sqlite
```

### Tier 2: Single-Node Production

```
┌──────────────┐
│ CLI/TUI/Web  │
└──────┬───────┘
       │ WebSocket
       ▼
┌──────────────┐
│  Soothe      │
│  Daemon      │
└──────┬───────┘
       │ PostgreSQL
       ▼
┌──────────────┐
│ PostgreSQL   │
│ + pgvector   │
└──────────────┘
```

**Best for**: Small teams, moderate load (<100 concurrent threads)

**Configuration**: See [Production Setup](production-setup.md)

### Tier 3: Multi-Node Production

```
┌──────────────┐
│ Load Balancer│
└──────┬───────┘
       │
       ├─→ ┌──────────────┐
       │   │ Soothe Node 1│
       │   └──────┬───────┘
       │          │
       ├─→ ┌──────────────┐
       │   │ Soothe Node 2│
       │   └──────┬───────┘
       │          │
       └─────→ ┌──────────────┐
               │ PostgreSQL   │
               │ Cluster      │
               └──────────────┘
```

**Best for**: High availability, large teams (>100 concurrent threads)

**Configuration**: See [Scaling Strategies](scaling.md)

## Deployment Checklist

Before deploying to production, verify:

### Infrastructure

- [ ] PostgreSQL database configured and accessible
- [ ] pgvector extension installed
- [ ] Network connectivity between daemon and database
- [ ] Persistent storage mounted (Docker volumes)
- [ ] Reverse proxy configured (if exposing WebSocket/HTTP)

### Security

- [ ] API keys stored securely (environment variables, secrets manager)
- [ ] TLS enabled on reverse proxy
- [ ] Authentication configured on reverse proxy
- [ ] Firewall rules set (database port, daemon ports)
- [ ] Security policy configured in `config.yml`

### Monitoring

- [ ] Langfuse observability enabled (optional but recommended)
- [ ] Log collection configured
- [ ] Health checks enabled in Docker Compose
- [ ] Alerting configured for critical errors

### Backup & Recovery

- [ ] PostgreSQL backup strategy implemented
- [ ] Disaster recovery plan documented
- [ ] Configuration files backed up
- [ ] Recovery testing performed

## Quick Start: Production Deployment

Using Docker Compose (recommended):

```bash
# 1. Clone deployment files
cd soothe/deploy

# 2. Configure environment
cp env-example .env
vim .env  # Set API keys, passwords

# 3. Create config.yml
cp config.prod.yml config.yml

# 4. Deploy stack
docker compose up -d

# 5. Verify deployment
docker compose ps
docker compose logs soothed
```

See [Production Setup](production-setup.md) for detailed steps.

## Deployment Patterns

### Pattern 1: Docker Compose (Recommended)

**Pros**:
- Single-command deployment
- Built-in health checks
- Automatic restarts
- Volume management
- Network isolation

**Use**: Standard production deployments

See: `deploy/docker-compose.yml` and [Production Setup](production-setup.md)

### Pattern 2: Kubernetes

**Pros**:
- Horizontal scaling
- Rolling updates
- Service mesh integration
- Advanced orchestration

**Use**: Large-scale, high-availability deployments

See: [Scaling Strategies](scaling.md)

### Pattern 3: Bare Metal / systemd

**Pros**:
- Maximum control
- No container overhead
- Direct hardware access

**Use**: Specialized environments, performance-critical applications

See: [Production Setup](production-setup.md#systemd-deployment)

## Common Deployment Scenarios

### Scenario 1: Development Team (10 users)

**Setup**:
- Single PostgreSQL instance (4 databases per RFC-802)
- Single Soothe daemon
- WebSocket transport (localhost)
- SQLite fallback for testing

**Config** (`config.yml` + `daemon.yml`):
```yaml
# config.yml
persistence:
  default_backend: postgresql
  postgres_base_dsn: postgresql://user:pass@postgres-host:5432
```
```yaml
# daemon.yml
transports:
  websocket:
    enabled: true
    host: 127.0.0.1
    port: 8765
thread_pool:
  request_timeout_seconds: 1209600  # 14d per turn; 0 = no cap
```

### Scenario 2: Production Team (50 users)

**Setup**:
- PostgreSQL + pgvector (production-grade)
- Reverse proxy (nginx) with TLS
- WebSocket transport
- Langfuse observability

**Config** (`config.yml` + `daemon.yml`):
```yaml
# config.yml
persistence:
  default_backend: postgresql
  
observability:
  langfuse:
    enabled: true
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
```
```yaml
# daemon.yml
transports:
  websocket:
    enabled: true
    host: 127.0.0.1
    port: 8765
thread_pool:
  request_timeout_seconds: 1209600
```

### Scenario 3: Large Organization (500 users)

**Setup**:
- PostgreSQL cluster (primary + replicas)
- Multiple Soothe nodes (horizontal scaling)
- Load balancer (nginx/HAProxy)
- Redis for distributed coordination
- Kafka for event streaming

**Config**: See [Scaling Strategies](scaling.md)

## Post-Deployment Tasks

After successful deployment:

### 1. Verify Connectivity

```bash
# Test daemon health
soothed status

# Test database connection
psql -h postgres-host -U user -d soothe_checkpoints -c "SELECT 1"

# Test API connectivity (if WebSocket/HTTP enabled)
curl http://localhost:8765/health
```

### 2. Configure Observability

```yaml
observability:
  langfuse:
    enabled: true
    host: https://your-langfuse-instance.com
  log_file_path: /var/log/soothe/soothed.log
  log_file_level: INFO
```

### 3. Set Up Monitoring

- Enable health checks in Docker Compose
- Configure log aggregation (ELK, Loki, etc.)
- Set up alerting (PagerDuty, Slack, etc.)

See [Monitoring Guide](monitoring.md)

### 4. Implement Backup Strategy

```bash
# PostgreSQL backup
pg_dump -h postgres-host -U user soothe_checkpoints > backup.sql

# Docker volume backup
docker run --rm -v soothe_postgres_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres_data.tar.gz /data
```

See [Backup Recovery](backup-recovery.md)

### 5. Security Hardening

```yaml
security:
  sandbox: false  # Enable for restrictive environments
  allow_paths_outside_workspace: false
  denied_paths:
    - /etc/**
    - ~/.ssh/**
    - ~/.aws/**
```

See [Security Hardening](security.md)

## Troubleshooting

### Deployment Issues

| Issue | Solution | Reference |
|-------|----------|-----------|
| PostgreSQL connection fails | Check DSN, credentials, firewall | [Production Setup](production-setup.md) |
| Daemon won't start | Check config.yml syntax, logs | [Troubleshooting](../troubleshooting.md) |
| WebSocket connection refused | Enable transport, check port | [Daemon Management](../daemon-management.md) |
| pgvector extension missing | Install extension, restart PostgreSQL | [Production Setup](production-setup.md) |

### Performance Issues

| Issue | Solution | Reference |
|-------|----------|-----------|
| Slow thread resumption | Tune PostgreSQL pool size | [Scaling Strategies](scaling.md) |
| Memory exhaustion | Limit parallel goals, adjust pool | [Scaling Strategies](scaling.md) |
| High latency | Enable connection pooling, optimize queries | [Scaling Strategies](scaling.md) |

## Next Steps

1. **Production Setup**: Follow [Production Setup Guide](production-setup.md) for detailed deployment steps
2. **Monitoring**: Configure observability with [Monitoring Guide](monitoring.md)
3. **Security**: Harden deployment with [Security Hardening](security.md)
4. **Scaling**: Plan growth with [Scaling Strategies](scaling.md)
5. **Backup**: Protect data with [Backup Recovery](backup-recovery.md)

## Related Documentation

- [Configuration Guide](../configuration-guide/index.md) - Complete YAML reference
- [Daemon Management](../daemon-management.md) - Daemon lifecycle
- [Transport Setup](../multi-transport.md) - WebSocket configuration
- [Authentication](../authentication.md) - Reverse proxy authentication
- [Troubleshooting](../troubleshooting.md) - Common issues and solutions

---

**Need help?** See [Troubleshooting](../troubleshooting.md) or check the [Soothe repository](https://github.com/mirasoth/soothe).