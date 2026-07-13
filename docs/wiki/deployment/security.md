---
title: "Security Hardening"
parent: Deployment
grand_parent: Wiki
nav_order: 3
description: >-
  Comprehensive security guide for production Soothe deployments, covering reverse proxies, TLS, and access control.
---

# Security Hardening Guide

Comprehensive security guide for production Soothe deployments.

## Overview

Soothe follows a **security by delegation** model (RFC-302, RFC-303):

- **No built-in authentication**: All auth handled by reverse proxy
- **No authorization layer**: Reverse proxy controls access
- **Internal trust model**: Daemon trusts reverse proxy connections

This guide covers:
- Reverse proxy security (TLS, authentication)
- Access control configuration
- Secrets management
- Network security
- Workspace security policies
- Database security

## Security Architecture

### Transport Security Model

```
┌──────────────┐
│ Web/Mobile   │
│   Client     │
└──────┬───────┘
       │ HTTPS/WSS (TLS)
       │ JWT/OAuth/API Key
       ▼
┌──────────────┐
│  Reverse     │  ← Authentication, TLS, Rate Limiting
│  Proxy       │     Access Control, Request Filtering
│ (nginx/etc.) │
└──────┬───────┘
       │ HTTP/WS (trusted)
       │ No auth (internal)
       ▼
┌──────────────┐
│  Soothe      │  ← No built-in auth (trusts reverse proxy)
│  Daemon      │     Workspace security policies
│              │     Host execution tools (run_command, run_background, …)
└──────────────┘
```

**Key principle**: Soothe daemon runs in trusted network zone, all security handled at reverse proxy boundary.

## Reverse Proxy Security (Required for WebSocket/HTTP)

### Why Reverse Proxy?

The WebSocket transport exposes daemon port 8765. This MUST be protected by reverse proxy:

**Security responsibilities**:
- TLS termination (HTTPS/WSS)
- Authentication (JWT, OAuth, API keys)
- Authorization (role-based access control)
- Rate limiting (prevent abuse)
- Request filtering (block malicious requests)
- IP whitelisting (restrict access)

### Recommended Reverse Proxies

| Proxy | Best For | Features |
|-------|----------|----------|
| **nginx** | Standard production | TLS, JWT, rate limiting |
| **Caddy** | Easy setup | Auto HTTPS, simple config |
| **Traefik** | Kubernetes/Docker | Auto-discovery, dynamic config |
| **HAProxy** | High performance | Advanced routing, health checks |
| **Envoy** | Service mesh | Advanced filtering, observability |

### Caddy Configuration (Simplest Option)

**Caddyfile** (automatic HTTPS + JWT auth):
```
soothe.example.com {
    encode gzip

    # JWT authentication (caddy-auth-jwt plugin)
    jwt {
        secret YOUR_JWT_SECRET
        signalg HS256
    }

    handle /ws {
        reverse_proxy localhost:8765
    }
}
```

**Soothe config**:
```yaml
transports:
  websocket:
    enabled: true
    host: "127.0.0.1"
    port: 8765
```

### nginx Configuration

#### TLS + Authentication (JWT or API Key)

```nginx
# WebSocket upstream
upstream soothe_ws {
    server 127.0.0.1:8765;
}

server {
    listen 443 ssl http2;
    server_name soothe.your-domain.com;

    # TLS
    ssl_certificate /etc/letsencrypt/live/soothe.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/soothe.your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=ws_limit:10m rate=10r/s;

    location /ws {
        limit_req zone=ws_limit burst=20 nodelay;

        # Option 1: JWT authentication (requires nginx-plus or auth_jwt module)
        # auth_jwt "Soothe API";
        # auth_jwt_key_file /etc/nginx/jwt_key.pem;

        # Option 2: API key header validation
        # if ($http_x_api_key = "") { return 401; }
        # if ($http_x_api_key != "your-api-key") { return 403; }

        proxy_pass http://soothe_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

**Client usage**:
```bash
# API key validated by reverse proxy (not Soothe)
soothe --daemon-host soothe.your-domain.com --daemon-port 443 -p "Check status"
```

#### OAuth 2.0 / OIDC (Enterprise)

Use [OAuth2 Proxy](https://oauth2-proxy.github.io/oauth2-proxy/) with nginx:

```yaml
# docker-compose.yml
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:v7.4.0
    environment:
      OAUTH2_PROXY_PROVIDER: oidc
      OAUTH2_PROXY_CLIENT_ID: <client_id>
      OAUTH2_PROXY_CLIENT_SECRET: <client_secret>
      OAUTH2_PROXY_OIDC_ISSUER_URL: https://accounts.google.com
      OAUTH2_PROXY_COOKIE_SECRET: <random_secret>
      OAUTH2_PROXY_UPSTREAM: http://soothed:8765

  soothed:
    image: registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

### Rate Limiting

**nginx rate limiting**:
```nginx
# Define rate limit zones
limit_req_zone $binary_remote_addr zone=ws_limit:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=ws_conn:10m;

# Apply rate limits
location /ws {
    limit_req zone=ws_limit burst=20 nodelay;
    limit_conn zone=ws_conn 10;
    
    proxy_pass http://soothe_ws;
}
```

**Rate limit parameters**:
- `rate=10r/s`: 10 requests per second per IP
- `burst=20`: Allow burst up to 20 requests
- `nodelay`: Process burst immediately
- `limit_conn 10`: Max 10 concurrent connections per IP

### IP Whitelisting

```nginx
location /ws {
    # Allow specific IPs
    allow 10.0.0.0/8;  # Internal network
    allow 192.168.1.0/24;  # Office network
    deny all;  # Block everyone else
    
    proxy_pass http://soothe_ws;
}
```

### Request Filtering

**Block malicious patterns**:
```nginx
location /ws {
    # Block suspicious user agents
    if ($http_user_agent ~* (bot|crawler|spider)) {
        return 403;
    }
    
    # Block large payloads
    client_max_body_size 1m;
    
    # Block specific headers
    if ($http_x_malicious_header) {
        return 403;
    }
    
    proxy_pass http://soothe_ws;
}
```

### CORS Configuration

Configure allowed origins for WebSocket connections:

```yaml
# ~/.soothe/config/daemon.yml
transports:
  websocket:
    cors_origins:
      - "https://app.example.com"
      - "https://soothe.example.com"
```

### TLS Best Practices

**Recommended TLS configuration**:
```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers on;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
ssl_stapling on;
ssl_stapling_verify on;
```

**Certificate management**:
- Use Let's Encrypt for automatic certs (Certbot)
- Use Caddy for auto HTTPS (simpler)
- Use managed certificates (AWS ACM, GCP Managed SSL)

```bash
# Let's Encrypt setup
sudo certbot --nginx -d soothe.your-domain.com
```

## Secrets Management

### Provider API Keys

**Never store API keys in config.yml!**

**Best practices**:

1. **Environment variables** (Docker):
   ```yaml
   # docker-compose.yml
   services:
     soothed:
       environment:
         OPENAI_API_KEY: ${OPENAI_API_KEY}
         OPENAI_BASE_URL: ${OPENAI_BASE_URL}
   ```
   
   **`.env` file** (not committed):
   ```bash
   OPENAI_API_KEY=sk-...
   OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # Optional for OpenAI-compatible
   ```

2. **Secrets manager** (Kubernetes):
   ```yaml
   # Kubernetes Secret
   apiVersion: v1
   kind: Secret
   metadata:
     name: soothe-secrets
   type: Opaque
   data:
     openai-api-key: <base64-encoded>
   ```

3. **Vault** (Enterprise):
   ```bash
   # HashiCorp Vault integration
   vault kv put secret/soothe openai_api_key=sk-...
   
   # Retrieve in deployment
   OPENAI_API_KEY=$(vault kv get -field=openai_api_key secret/soothe)
   ```

4. **AWS Secrets Manager**:
   ```bash
   # Store secret
   aws secretsmanager create-secret \
     --name soothe/openai-api-key \
     --secret-string "sk-..."
   
   # Retrieve in deployment
   OPENAI_API_KEY=$(aws secretsmanager get-secret-value \
     --secret-id soothe/openai-api-key \
     --query SecretString --output text)
   ```

### Config File Security

```bash
# Config file permissions
chmod 600 ~/.soothe/config/config.yml  # User-only
chown $USER ~/.soothe/config/config.yml

# Production deployment
sudo chmod 600 /var/lib/soothe/config/config.yml
sudo chown soothe:soothe /var/lib/soothe/config/config.yml
```

### Database Credentials

**PostgreSQL password security**:
```bash
# Use strong password (32+ chars)
openssl rand -base64 32 > postgres_password.txt

# Store in .env (not committed)
echo "POSTGRES_PASSWORD=$(cat postgres_password.txt)" >> .env

# Or use secrets manager
vault kv put secret/soothe/postgres password=$(cat postgres_password.txt)
```

**PostgreSQL TLS**:
```yaml
persistence:
  postgres_base_dsn: postgresql://user:pass@host:5432?sslmode=require
```

## Network Security

### Network Segmentation

**Recommended network zones**:

```
┌─────────────────┐  Zone 1: Public
│  Reverse Proxy  │  (TLS termination, auth)
│  (nginx)        │
└────────┬────────┘
         │ Trusted network
         ↓
┌─────────────────┐  Zone 2: Application
│  Soothe Daemon  │  (No auth, internal trust)
└────────┬────────┘
         │ Database network
         ↓
┌─────────────────┐  Zone 3: Database
│  PostgreSQL     │  (Restricted access)
│  + pgvector     │
└─────────────────┘
```

**Docker network isolation**:
```yaml
networks:
  soothe-public:  # Reverse proxy → Daemon
    driver: bridge
  soothe-app:     # Daemon → PostgreSQL
    driver: bridge
  soothe-db:      # PostgreSQL internal
    driver: bridge
    internal: true  # No external access
```

### Firewall Rules

**Production firewall configuration**:

```bash
# Enable UFW
sudo ufw enable

# Allow SSH
sudo ufw allow 22/tcp

# Allow HTTPS (reverse proxy)
sudo ufw allow 443/tcp

# Block direct daemon access
sudo ufw deny 8765/tcp  # WebSocket

# Block direct PostgreSQL access
sudo ufw deny 5432/tcp

# Allow internal network (Docker)
sudo ufw allow from 172.16.0.0/12  # Docker bridge network

# Allow internal network (systemd)
sudo ufw allow from 10.0.0.0/8
sudo ufw allow from 192.168.0.0/16
```

### VPC Network Security (Cloud)

**AWS VPC configuration**:
- Private subnet for PostgreSQL (no public IP)
- Private subnet for Soothe daemon
- Public subnet for reverse proxy (ALB/nginx)
- Security groups:
  - Reverse proxy: Allow inbound HTTPS (0.0.0.0/0)
  - Daemon: Allow inbound from reverse proxy SG only
  - PostgreSQL: Allow inbound from daemon SG only

**GCP VPC configuration**:
- Private VPC for PostgreSQL + Soothe daemon
- Public subnet for reverse proxy
- Firewall rules:
  - Allow HTTPS ingress to reverse proxy
  - Allow internal traffic: reverse proxy → daemon → PostgreSQL

## Workspace Security Policies

Soothe provides workspace-level security policies in `config.yml`:

### Security Configuration

```yaml
security:
  # Workspace access control
  allow_paths_outside_workspace: false
  require_approval_for_outside_paths: true
  
  # Denied paths (system directories, secrets)
  denied_paths:
    - /etc/**
    - /bin/**
    - /sbin/**
    - /usr/**
    - /System/**
    - /Library/**
    - /private/etc/**
    - ~/.ssh/**
    - ~/.gnupg/**
    - ~/.aws/**
    - '**/.env'
    - '**/credentials.json'
    - '**/secrets.json'
  
  # Allowed paths (whitelist)
  allowed_paths:
    - '**'  # Allow all within workspace (adjust for stricter control)
  
  # File type restrictions
  denied_file_types: []  # Block specific extensions
  require_approval_for_file_types:
    - .env
    - .pem
    - .key
    - .credentials
```

### Security Policy Profiles

**Standard Development**:
```yaml
security:
  allow_paths_outside_workspace: false
  denied_paths: [/etc/**, ~/.ssh/**, ~/.aws/**]
  require_approval_for_file_types: [.env]
```

**Strict Production** (add these to standard):
```yaml
security:
  require_approval_for_outside_paths: true
  denied_paths: [/etc/**, /bin/**, ~/.ssh/**, ~/.aws/**, ~/.gnupg/**, '**/.env']
  denied_file_types: [.key, .pem, .p12]
```

**Maximum Security** (restrict workspace scope):
```yaml
security:
  allow_paths_outside_workspace: false
  allowed_paths: ['/workspace/project-a/**', '/workspace/project-b/**']
  denied_file_types: [.env, .key, .pem, .credentials]
```

### Workspace Isolation (Multi-Team)

### Workspace Isolation (Multi-Team)

**Pattern: Workspace reservation** (RFC-222):

```yaml
agent:
  autonomous:
    workspace_reservation:
      enabled: true
      strict_overlap: true
```

**How it works**:
- Prevents concurrent goals on overlapping workspace prefixes
- `/workspace/project-a` conflicts with `/workspace/project-a/subdir`
- Team A and Team B cannot modify same workspace simultaneously

## Database Security

### PostgreSQL Security

**Connection security**:
```bash
# PostgreSQL configuration
# /etc/postgresql/17/main/pg_hba.conf

# Allow connections from daemon only
host soothe_checkpoints soothe_user 10.0.0.0/8 scram-sha-256
host soothe_metadata soothe_user 10.0.0.0/8 scram-sha-256
host soothe_vectors soothe_user 10.0.0.0/8 scram-sha-256
host soothe_memory soothe_user 10.0.0.0/8 scram-sha-256

# Block external connections
local all all reject
host all all 0.0.0.0/0 reject
```

**TLS configuration**:
```bash
# /etc/postgresql/17/main/postgresql.conf
ssl = on
ssl_cert_file = '/etc/postgresql/17/main/server.crt'
ssl_key_file = '/etc/postgresql/17/main/server.key'
```

**User permissions**:
```sql
-- Create restricted user
CREATE USER soothe_user WITH PASSWORD 'secure_password';

-- Grant limited permissions
GRANT CONNECT ON DATABASE soothe_checkpoints TO soothe_user;
GRANT USAGE ON SCHEMA public TO soothe_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO soothe_user;

-- Restrict dangerous operations
REVOKE CREATE ON SCHEMA public FROM soothe_user;
```

**Encryption at rest**:
```bash
# PostgreSQL transparent data encryption (TDE)
# Use cloud provider encrypted volumes:
# - AWS EBS encryption
# - GCP Persistent Disk encryption
# - Azure Disk Encryption

# Or use filesystem encryption:
cryptsetup luksFormat /dev/sdb
cryptsetup luksOpen /dev/sdb postgres_encrypted
mkfs.ext4 /dev/mapper/postgres_encrypted
mount /dev/mapper/postgres_encrypted /var/lib/postgresql
```

### Database Access Control

**Separate databases for isolation** (RFC-802):
```sql
-- Checkpoints database (LangGraph + StrangeLoop)
CREATE DATABASE soothe_checkpoints OWNER soothe_user;

-- Metadata database (Thread lifecycle)
CREATE DATABASE soothe_metadata OWNER soothe_user;

-- Vectors database (pgvector embeddings)
CREATE DATABASE soothe_vectors OWNER soothe_user;
CREATE EXTENSION vector;

-- Memory database (MemU semantic memory)
CREATE DATABASE soothe_memory OWNER soothe_user;
```

**Benefits**:
- Separate backup policies per database
- Different access control per database
- Performance isolation (connection pools)
- Granular disaster recovery

## Container Security (Docker)

### Docker Security Best Practices

**User isolation**:
```yaml
services:
  soothed:
    user: "1000:1000"  # Non-root user (UID:GID)
```

**Capability restrictions**:
```yaml
services:
  soothed:
    cap_drop:
      - ALL  # Drop all capabilities
    cap_add:
      - NET_BIND_SERVICE  # Only needed capabilities
```

**Read-only filesystem**:
```yaml
services:
  soothed:
    read_only: true
    tmpfs:
      - /tmp
      - /var/tmp
```

**Resource limits**:
```yaml
services:
  soothed:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

**Security options**:
```yaml
services:
  soothed:
    security_opt:
      - no-new-privileges:true
      - seccomp:unconfined  # Adjust based on needs
```

### Docker Network Security

```yaml
networks:
  soothe-internal:
    driver: bridge
    internal: true  # No external access
```

### Image Security

**Use trusted images**:
```yaml
services:
  soothed:
    image: registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
    # Verify image signature (if using signed images)
```

**Scan images for vulnerabilities**:
```bash
# Trivy scan
trivy image registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest

# Docker scan
docker scan registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

## systemd Security Hardening

**`/etc/systemd/system/soothed.service`**:
```ini
[Service]
# Prevent privilege escalation
NoNewPrivileges=true

# Isolate filesystem
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true

# Restrict network access
PrivateNetwork=false  # Needed for PostgreSQL connection
RestrictAddressFamilies=AF_INET AF_INET6

# Restrict user namespace
RestrictSUIDSGID=true

# Allow only specific paths
ReadWritePaths=/var/lib/soothe /var/log/soothe

# Lock memory (prevent swapping)
MemoryDenyWriteExecute=true

# CPU/memory limits
LimitCPU=2
MemoryMax=4G
```

## Security Checklist

### Pre-Deployment Security Checklist

- [ ] Reverse proxy configured with TLS
- [ ] Authentication configured (JWT/API key/OAuth)
- [ ] Rate limiting enabled
- [ ] IP whitelisting configured (if needed)
- [ ] Firewall rules set (block direct daemon access)
- [ ] Secrets stored securely (environment vars/secrets manager)
- [ ] Config file permissions set (600)
- [ ] PostgreSQL TLS enabled
- [ ] PostgreSQL user permissions restricted
- [ ] Security policy configured in config.yml
- [ ] Docker security options set (user, capabilities, read-only)
- [ ] Image vulnerabilities scanned

### Ongoing Security Tasks

**Daily**:
```bash
# Check TLS certificate expiration
sudo certbot certificates

# Review authentication logs
sudo tail -f /var/log/nginx/access.log | grep -E "401|403"

# Monitor rate limit violations
sudo tail -f /var/log/nginx/error.log | grep "limiting"
```

**Weekly**:
```bash
# Rotate secrets (if policy requires)
# Update API keys in secrets manager

# Review security policy violations
grep "Permission denied" ~/.soothe/logs/soothed.log

# Scan for vulnerabilities
trivy image registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

**Monthly**:
```bash
# Audit firewall rules
sudo ufw status numbered

# Review PostgreSQL access logs
sudo -u postgres psql -c "SELECT * FROM pg_stat_activity"

# Update TLS certificates (auto-renew with Certbot)
sudo certbot renew
```

## Security Incident Response

### Common Security Issues

**Issue 1: Unauthorized Access Detected**

**Symptoms**: Unexpected connections in nginx logs
```
2026-06-06 10:30:45 [error] 401 Unauthorized: IP 1.2.3.4
```

**Response**:
1. Check authentication configuration
2. Verify API keys/JWT tokens
3. Review reverse proxy logs
4. Block suspicious IPs if pattern detected:
   ```bash
   sudo ufw deny from 1.2.3.4
   ```

**Issue 2: Rate Limit Exhaustion**

**Symptoms**: Rate limit errors in nginx
```
2026-06-06 10:35:00 [error] limiting requests, client: 1.2.3.4
```

**Response**:
1. Identify attack source (log analysis)
2. Temporary IP block:
   ```bash
   sudo ufw deny from 1.2.3.4
   ```
3. Adjust rate limits if legitimate traffic spike:
   ```nginx
   limit_req zone=ws_limit burst=50;  # Increase burst
   ```

**Issue 3: Secrets Exposed**

**Symptoms**: API keys visible in logs or config files

**Response**:
1. Immediately rotate exposed secrets
2. Update secrets in secrets manager
3. Remove secrets from logs/files
4. Audit for unauthorized usage
5. Investigate exposure cause

**Issue 4: PostgreSQL Connection from External**

**Symptoms**: Connection attempts from unexpected IPs

**Response**:
1. Check pg_hba.conf configuration
2. Verify firewall rules
3. Block external access:
   ```bash
   sudo ufw deny 5432/tcp
   ```
4. Audit PostgreSQL logs for successful connections

## Security Monitoring

### Authentication Monitoring

```bash
# Monitor authentication failures
sudo tail -f /var/log/nginx/error.log | grep -E "401|403"

# Count auth failures by IP
sudo awk '/401|403/ {print $1}' /var/log/nginx/access.log | sort | uniq -c
```

### Rate Limit Monitoring

```bash
# Monitor rate limit violations
sudo tail -f /var/log/nginx/error.log | grep "limiting"

# Count violations by IP
sudo awk '/limiting/ {print $1}' /var/log/nginx/error.log | sort | uniq -c
```

### PostgreSQL Connection Monitoring

```bash
# Monitor PostgreSQL connections
sudo -u postgres psql -c "SELECT * FROM pg_stat_activity"

# Check for external connections
sudo -u postgres psql -c "
  SELECT client_addr, count(*) 
  FROM pg_stat_activity 
  GROUP BY client_addr
"
```

## Next Steps

After security hardening:

1. **Monitoring**: Verify security metrics → [Monitoring Guide](monitoring.md)
2. **Backup**: Protect secrets and data → [Backup Recovery](backup-recovery.md)
3. **Scaling**: Secure scaling strategies → [Scaling Strategies](scaling.md)

## Related Documentation

- [Deployment Guide](index.md) - Deployment overview
- [Production Setup](production-setup.md) - Deployment steps
- [Authentication](../authentication.md) - Reverse proxy authentication
- [Multi-Transport](../multi-transport.md) - Transport security
- [Configuration Guide](../configuration-guide/index.md) - Security policy settings

---

**Security questions?** See [Authentication Guide](../authentication.md) or [Troubleshooting](../troubleshooting.md).