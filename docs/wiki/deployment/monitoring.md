# Monitoring and Observability Guide

Comprehensive guide for monitoring Soothe daemon, tracking LLM usage, and setting up observability.

## Overview

Soothe provides multiple observability layers:

1. **Langfuse Integration**: LLM traces, token usage, cost tracking
2. **Structured Logging**: Daemon logs, thread activity, errors
3. **Health Checks**: Docker/container health monitoring
4. **Thread Auditing**: Conversation history and goal execution logs
5. **Metrics**: Performance counters (via logging)

## Langfuse Integration (Recommended)

Langfuse provides comprehensive LLM observability: request traces, token counts, latency, cost tracking, and debugging.

### Setup Langfuse

#### Option 1: Self-Hosted Langfuse (Docker)

Use the development Docker Compose stack:

```bash
# Start Langfuse + dependencies
docker compose -f docker-compose.dev.yml up -d

# Langfuse UI: http://localhost:3300
# Default credentials:
#   Email: dev@soothe.local
#   Password: SootheLangfuseLocalDev1
```

**Services started**:
- `langfuse-web`: Web UI and API (port 3300)
- `langfuse-worker`: Background processing
- `langfuse-postgres`: Langfuse metadata
- `langfuse-clickhouse`: Observability data
- `langfuse-redis`: Job queue
- `langfuse-minio`: Blob storage

#### Option 2: Langfuse Cloud

```bash
# Sign up at https://langfuse.com
# Create project → Get API keys
```

### Configure Soothe for Langfuse

```yaml
observability:
  langfuse:
    enabled: true
    public_key: "${LANGFUSE_PUBLIC_KEY}"
    secret_key: "${LANGFUSE_SECRET_KEY}"
    host: "${LANGFUSE_HOST}"  # http://localhost:3300 (self-hosted) or https://cloud.langfuse.com
    environment: production
    sample_rate: 1.0  # Sample all traces (set lower for high-volume)
    trace_name: soothe_goal_execution
    tags:
      - soothe
      - production
    user_id: team-member-id  # Optional: User attribution
```

**Environment variables**:
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3300  # Or https://cloud.langfuse.com
```

### Langfuse Features in Soothe

**Tracked automatically**:
- All LLM calls (CoreAgent, AgentLoop, subagents)
- Token usage (prompt + completion)
- Latency per call
- Model selection (default/fast/think roles)
- Goal execution context
- Plan/Execute phase traces

**Trace structure**:
```
Goal Execution (trace)
  ├─ Plan Phase (span)
  │   ├─ LLM: Plan generation
  │   ├─ LLM: Plan assessment
  │   └─ Subagent: explore
  │       └─ LLM: File search reasoning
  ├─ Execute Phase (span)
  │   ├─ LLM: Execute reasoning
  │   ├─ Tool: read_file (x3)
  │   ├─ LLM: Execute reasoning (iteration 2)
  │   └─ Tool: edit_file
  └─ Goal Completion (span)
      └─ LLM: Synthesis
```

### Langfuse Dashboard Usage

**View traces**:
1. Open Langfuse UI (http://localhost:3300)
2. Navigate to "Traces" section
3. Filter by:
   - Time range
   - User ID (if configured)
   - Model name
   - Tags (`soothe`, `production`)

**Key metrics**:
- **Total tokens**: Cost tracking
- **Average latency**: Performance monitoring
- **Model distribution**: Usage patterns
- **Error rate**: Failure detection

**Example queries**:
```sql
-- High-cost traces (Langfuse ClickHouse)
SELECT 
  trace_id,
  sum(total_tokens) as total_tokens,
  sum(latency_ms) as total_latency
FROM traces
WHERE timestamp > now() - INTERVAL 1 DAY
GROUP BY trace_id
ORDER BY total_tokens DESC
LIMIT 10;
```

### Cost Tracking

**Token cost estimation**:
```python
# Example: GPT-4o-mini pricing
prompt_cost = prompt_tokens * 0.15 / 1_000_000  # $0.15 per 1M tokens
completion_cost = completion_tokens * 0.60 / 1_000_000  # $0.60 per 1M tokens
total_cost = prompt_cost + completion_cost
```

**Langfuse dashboard**:
- "Usage" tab → Daily/Monthly token counts
- "Cost" tracking → Model-specific pricing

### Langfuse Best Practices

**Production recommendations**:
1. **Sampling**: Use `sample_rate` for high-volume deployments
   ```yaml
   observability:
     langfuse:
       sample_rate: 0.1  # Sample 10% of traces (cost reduction)
   ```

2. **User attribution**: Set `user_id` for team tracking
   ```yaml
   user_id: "${SOOTHE_USER_ID}"  # Environment variable per user
   ```

3. **Environment tagging**: Separate dev/prod traces
   ```yaml
   environment: "${ENVIRONMENT}"  # dev, staging, production
   ```

4. **Tags**: Add custom tags for filtering
   ```yaml
   tags:
     - soothe
     - team-alpha
     - project-x
   ```

## Structured Logging

Soothe emits structured JSON logs for daemon activity, thread execution, and errors.

### Log Locations

**Default paths**:
```bash
~/.soothe/logs/               # Daemon logs (SOOTHE_HOME)
~/.soothe/runs/               # Thread execution logs
/var/log/soothe/              # Production deployment (Docker/systemd)
```

### Configure Logging

```yaml
observability:
  log_file_path: /var/log/soothe/daemon.log
  log_file_level: INFO
  log_file_max_bytes: 5242880  # 5 MB
  log_file_backup_count: 3
  
  console:
    enabled: true
    level: WARNING
    stream: stderr
    format: '%(level_short)s %(name)s %(message)s'
  
  verbosity: normal  # minimal | normal | detailed | debug
  
  thread_logging_enabled: true
  thread_logging_retention_days: 30
  thread_logging_max_size_mb: 100
```

**Verbosity levels**:

| Level | Logs Included | Use Case |
|-------|---------------|----------|
| `minimal` | Errors only | Production (minimal overhead) |
| `normal` | Protocol events + errors | Standard monitoring |
| `detailed` | Subagent events + tool calls | Debugging |
| `debug` | All events + heartbeat | Deep debugging |

### Log Structure

**Daemon log example**:
```json
{
  "timestamp": "2026-06-06T02:40:00Z",
  "level": "INFO",
  "logger": "soothe.daemon.server",
  "message": "Goal dispatched to worker",
  "goal_id": "goal-abc123",
  "thread_id": "thread-xyz789",
  "workspace": "/var/lib/soothe/workspaces/project1",
  "iteration": 3,
  "phase": "execute"
}
```

**Thread log example**:
```json
{
  "timestamp": "2026-06-06T02:40:15Z",
  "level": "DEBUG",
  "logger": "soothe.core.agent_loop",
  "message": "Tool invocation completed",
  "tool_name": "read_file",
  "execution_time_ms": 150,
  "success": true,
  "thread_id": "thread-xyz789"
}
```

### Log Aggregation

**ELK Stack (Elasticsearch + Logstash + Kibana)**:

```yaml
# Filebeat configuration
filebeat.inputs:
  - type: log
    paths:
      - /var/log/soothe/*.log
    json.keys_under_root: true
    json.add_error_key: true

output.logstash:
  hosts: ["logstash:5044"]
```

**Loki (Grafana Stack)**:

```yaml
# Promtail configuration
scrape_configs:
  - job_name: soothe
    static_configs:
      - targets:
          - localhost
        labels:
          job: soothe
          __path__: /var/log/soothe/*.log
```

### Real-Time Log Monitoring

```bash
# Monitor daemon logs
tail -f ~/.soothe/logs/daemon.log

# Docker logs
docker compose logs -f soothed

# systemd logs
sudo journalctl -u soothed -f

# Filter by level
tail -f ~/.soothe/logs/daemon.log | grep "ERROR"

# Filter by thread
tail -f ~/.soothe/logs/daemon.log | grep "thread-xyz789"
```

### Log Analysis Queries

**Find slow operations**:
```bash
grep "execution_time_ms" daemon.log | \
  awk -F'"execution_time_ms":' '{print $2}' | \
  awk -F',' '{print $1}' | \
  sort -n | tail -20
```

**Count errors by type**:
```bash
grep "ERROR" daemon.log | \
  awk -F'"message":"' '{print $2}' | \
  awk -F'"' '{print $1}' | \
  sort | uniq -c
```

**Thread execution summary**:
```bash
# Extract thread IDs
grep "thread_id" daemon.log | \
  awk -F'"thread_id":"' '{print $2}' | \
  awk -F'"' '{print $1}' | \
  sort -u
```

## Health Checks

### Docker Health Checks

Built into `deploy/docker-compose.yml`:

```yaml
services:
  soothe-pgvector:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 20s
  
  soothed:
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import socket; ...'"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

**Monitor health status**:
```bash
docker compose ps

# Expected output:
# NAME              STATUS
# soothe-pgvector-1 Up (healthy)
# soothed-1         Up (healthy)
```

### HTTP Health Endpoint

Enable HTTP REST transport for health endpoint:

```yaml
daemon:
  transports:
    http_rest:
      enabled: true
      host: "0.0.0.0"
      port: 8766
```

**Health check endpoint**:
```bash
curl http://localhost:8766/health

# Response:
{
  "status": "healthy",
  "daemon_uptime_seconds": 3600,
  "active_threads": 5,
  "postgresql_connected": true,
  "memory_usage_mb": 256
}
```

### systemd Health Monitoring

```bash
# Check service status
sudo systemctl status soothed

# Active: active (running)

# Check recent logs
sudo journalctl -u soothed -n 50
```

### PostgreSQL Health

```bash
# Check PostgreSQL connection
docker compose exec soothe-pgvector pg_isready -U postgres

# Check database sizes
docker compose exec soothe-pgvector psql -U postgres -c "
  SELECT datname, pg_size_pretty(pg_database_size(datname))
  FROM pg_database
  WHERE datname LIKE 'soothe_%';
"

# Check connection count
docker compose exec soothe-pgvector psql -U postgres -c "
  SELECT count(*) FROM pg_stat_activity;
"
```

## Thread Auditing

Soothe maintains detailed logs for each thread/goal execution.

### Thread Log Location

```bash
~/.soothe/runs/<run-id>/threads/<thread-id>/conversation.json
~/.soothe/runs/<run-id>/threads/<thread-id>/goal_log.json
```

### Thread Log Configuration

```yaml
observability:
  thread_logging_enabled: true
  thread_logging_retention_days: 30
  thread_logging_max_size_mb: 100
  
  global_history:
    enabled: true
    max_size: 5000
    dedup_window: 10
    retention_days: 90
```

### Thread Log Structure

**`conversation.json`**: Full conversation history
```json
{
  "thread_id": "thread-xyz789",
  "created_at": "2026-06-06T02:40:00Z",
  "messages": [
    {
      "role": "user",
      "content": "List Python files",
      "timestamp": "2026-06-06T02:40:05Z"
    },
    {
      "role": "assistant",
      "content": "Found 15 Python files...",
      "timestamp": "2026-06-06T02:40:30Z"
    }
  ]
}
```

**`goal_log.json`**: Goal execution phases
```json
{
  "goal_id": "goal-abc123",
  "phases": [
    {
      "phase": "plan",
      "iterations": 1,
      "llm_calls": 2,
      "tools_invoked": ["explore"],
      "duration_seconds": 5.2
    },
    {
      "phase": "execute",
      "iterations": 3,
      "llm_calls": 4,
      "tools_invoked": ["read_file", "grep", "edit_file"],
      "duration_seconds": 12.5
    }
  ]
}
```

### Thread Auditing Use Cases

**Performance analysis**:
```bash
# Extract execution time per goal
cat ~/.soothe/runs/*/threads/*/goal_log.json | \
  jq '.phases[] | {phase, duration_seconds}'
```

**Tool usage patterns**:
```bash
# Count tool invocations
cat ~/.soothe/runs/*/threads/*/goal_log.json | \
  jq '[.phases[].tools_invoked[]]' | \
  jq 'group_by(.) | map({tool: .[0], count: length})'
```

**Error investigation**:
```bash
# Find failed goals
grep -r "ERROR" ~/.soothe/runs/*/threads/*/conversation.json
```

## Metrics and Performance Monitoring

### Key Metrics

**LLM Metrics** (via Langfuse):
- Total tokens per day/week/month
- Average latency per LLM call
- Model distribution (default/fast/think usage)
- Error rate (% failed LLM calls)

**Daemon Metrics** (via logs):
- Active threads
- Goal execution latency
- Tool invocation count
- Memory usage

**Database Metrics** (PostgreSQL):
- Connection pool size
- Query latency
- Database size growth
- Checkpoint write rate

### Performance Counters (via Logging)

Enable detailed metrics logging:

```yaml
observability:
  verbosity: detailed
  log_file_level: INFO
```

**Metric log examples**:
```json
{
  "metric": "llm_call_latency",
  "value_ms": 1250,
  "model": "gpt-4o-mini",
  "role": "default",
  "tokens_prompt": 850,
  "tokens_completion": 420
}

{
  "metric": "tool_execution",
  "tool": "read_file",
  "execution_time_ms": 150,
  "success": true
}

{
  "metric": "goal_duration",
  "goal_id": "goal-abc123",
  "duration_seconds": 18.5,
  "iterations": 3,
  "llm_calls": 6
}
```

### Grafana Dashboard Setup

**Data sources**:
1. **Loki**: Log aggregation
2. **PostgreSQL**: Thread counts, database size
3. **Langfuse**: LLM metrics (via ClickHouse)

**Example Grafana queries**:

**LLM call latency** (Loki):
```logql
{job="soothe"} | json | line_format "{{.value_ms}}" | metric_name="llm_call_latency"
```

**Active threads** (PostgreSQL):
```sql
SELECT count(*) FROM threads WHERE status = 'active';
```

**Database size** (PostgreSQL):
```sql
SELECT 
  datname,
  pg_size_pretty(pg_database_size(datname)) as size
FROM pg_database
WHERE datname LIKE 'soothe_%';
```

### Alerting Rules

**Critical alerts**:

1. **LLM error rate > 5%**:
   ```yaml
   alert: llm_error_rate_high
   expr: rate(llm_errors[5m]) / rate(llm_calls[5m]) > 0.05
   severity: critical
   ```

2. **PostgreSQL connection exhaustion**:
   ```yaml
   alert: postgres_connections_exhausted
   expr: postgres_connections > 180
   severity: critical
   ```

3. **Daemon memory > 3GB**:
   ```yaml
   alert: daemon_memory_high
   expr: daemon_memory_mb > 3000
   severity: warning
   ```

4. **Goal execution timeout**:
   ```yaml
   alert: goal_execution_timeout
   expr: goal_duration_seconds > 300
   severity: warning
   ```

## Monitoring Checklist

### Production Monitoring Setup

- [ ] Langfuse enabled with API keys
- [ ] Log aggregation configured (ELK/Loki)
- [ ] Health checks verified (Docker/systemd)
- [ ] Grafana dashboards created
- [ ] Alerting rules configured
- [ ] Thread auditing enabled
- [ ] Log retention policy set

### Daily Monitoring Tasks

```bash
# Check daemon health
docker compose ps

# Check PostgreSQL health
docker compose exec soothe-pgvector pg_isready

# Review recent errors
grep "ERROR" ~/.soothe/logs/daemon.log | tail -20

# Check Langfuse traces
# Open http://localhost:3300 → Traces → Last 24 hours

# Review thread activity
psql -h postgres-host -U user -d soothe_metadata \
  -c "SELECT count(*), status FROM threads GROUP BY status"
```

### Weekly Monitoring Tasks

```bash
# Token usage summary (Langfuse dashboard)
# Navigate to "Usage" tab

# Database size growth
psql -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database WHERE datname LIKE 'soothe_%'"

# Log retention cleanup
find ~/.soothe/logs -name "*.log" -mtime +30 -delete

# Thread log cleanup
find ~/.soothe/runs -type d -mtime +30 -exec rm -rf {} +
```

## Troubleshooting Monitoring Issues

### Langfuse Connection Failed

**Error**: `Langfuse connection error` or `Failed to send trace`

**Solution**:
1. Check Langfuse service running: `docker compose ps langfuse-web`
2. Verify API keys: `docker compose exec soothed env | grep LANGFUSE`
3. Test Langfuse API:
   ```bash
   curl -H "Authorization: Bearer ${LANGFUSE_SECRET_KEY}" \
     ${LANGFUSE_HOST}/api/public/v1/traces
   ```

### Log File Permissions

**Error**: `Permission denied: /var/log/soothe/daemon.log`

**Solution**:
```bash
# Fix permissions
sudo chown -R soothe:soothe /var/log/soothe
sudo chmod 755 /var/log/soothe
sudo chmod 644 /var/log/soothe/daemon.log
```

### PostgreSQL Monitoring Connection

**Error**: `psql: connection refused`

**Solution**:
```bash
# Check PostgreSQL running
docker compose exec soothe-pgvector pg_isready

# Check network connectivity
docker compose exec soothed ping soothe-pgvector

# Verify credentials
docker compose exec soothe-pgvector psql -U postgres -d soothe_metadata -c "SELECT 1"
```

## Advanced Observability Patterns

### Pattern 1: Full Stack Observability

```
┌─────────────┐
│  Langfuse   │  ← LLM traces, tokens, cost
└─────────────┘
       ↓
┌─────────────┐
│  Grafana    │  ← Dashboards, alerting
└─────────────┘
       ↓
┌─────────────────┬──────────────┐
│ Loki            │ PostgreSQL   │
│ (Logs)          │ (Metrics)    │
└─────────────────┴──────────────┘
```

### Pattern 2: Minimal Production Monitoring

```
┌─────────────┐
│  Langfuse   │  ← LLM traces (sample_rate: 0.1)
│  (Cloud)    │
└─────────────┘
       ↓
┌─────────────┐
│  File logs  │  ← INFO level, 30-day retention
│  + grep     │
└─────────────┘
```

### Pattern 3: Debugging Setup

```
┌─────────────┐
│  Langfuse   │  ← Full traces (sample_rate: 1.0)
│  (Local)    │
└─────────────┘
       ↓
┌─────────────┐
│  Debug logs │  ← verbosity: debug, detailed
└─────────────┘
       ↓
┌─────────────┐
│ Thread logs │  ← Full conversation audit
└─────────────┘
```

## Next Steps

After setting up monitoring:

1. **Security**: Configure secure monitoring → [Security Hardening](security.md)
2. **Scaling**: Plan for monitoring growth → [Scaling Strategies](scaling.md)
3. **Backup**: Protect monitoring data → [Backup Recovery](backup-recovery.md)

## Related Documentation

- [Deployment Guide](README.md) - Production deployment overview
- [Production Setup](production-setup.md) - Deployment steps
- [Configuration Guide](../configuration-guide/README.md) - Observability settings
- [Debugging Guide](../howto_debug.md) - Detailed debugging with logs
- [Langfuse Documentation](https://langfuse.com/docs)

---

**Need help?** See [Troubleshooting](../troubleshooting.md) or check Langfuse logs.