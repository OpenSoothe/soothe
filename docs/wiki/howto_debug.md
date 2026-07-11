---
title: Debug Guide
parent: Troubleshooting & Debugging
nav_order: 2
description: >-
  Comprehensive guide for debugging Soothe agents and diagnosing issues.
---

# Soothe Debug Guide

Comprehensive guide for debugging Soothe agents and diagnosing issues.

---

## 📁 Log Locations

Soothe maintains multiple log files in `~/.soothe/` for different purposes:

### Main Log Files

| Log File | Purpose |
|----------|---------|
| `~/.soothe/logs/soothed.log` | Daemon backend (agent execution, protocols, tools) |
| `~/.soothe/logs/soothe-cli.log` | CLI client (connection, UI, event handling) |
| `~/.soothe/data/threads/{thread_id}/logs/` | Thread conversation audit (when `thread_logging.enabled`) |
| `~/.soothe/data/langgraph_checkpoints.db` | LangGraph checkpoint database |
| `~/.soothe/data/metadata.db` | Metadata database |

---

## 🔧 Enabling Debug Logging

### Option 1: Environment Variables (Quick Debug)

Enable debug mode instantly without modifying config files:

```bash
# Enable global debug mode (affects both daemon and CLI)
export SOOTHE_DEBUG=true

# Or set specific log levels (overrides config file settings)
export SOOTHE_LOG_LEVEL=DEBUG  # Sets file logging to DEBUG for both daemon and CLI

# Then restart daemon and run CLI
soothed stop
soothed start
soothe
```

**When to use**: Quick debugging during development or troubleshooting specific issues without permanently changing config.

### Option 2: Configuration Files (Persistent Debug)

Enable debug logging permanently in configuration files:

#### 1. Enable Daemon Backend Debug Logs

Edit `~/.soothe/config/config.yml`:

```yaml
# Global debug flag (enables verbose agent behavior logging)
debug: true

# Daemon backend file logging (agent execution, protocols, tools, subagents)
logging:
  file:
    level: DEBUG        # DEBUG | INFO | WARNING | ERROR
    path: ""            # Empty = ~/.soothe/logs/soothed.log
    max_bytes: 5242880  # 5 MB before rotation
    backup_count: 3     # Number of rotating backups

  # Thread conversation logging (audit trail for each conversation)
  thread_logging:
    enabled: true       # Enable thread-specific logs
    dir: ""             # Empty = ~/.soothe/data/threads/{thread_id}/logs/
    retention_days: 30  # Auto-delete old threads

# LLM traces: enable Langfuse in observability (see config template observability.langfuse)
```

#### 2. Enable CLI Client Debug Logs

Pass `--log-level DEBUG` when invoking the CLI (or set `SOOTHE_LOG_LEVEL=DEBUG`):

```bash
soothe --log-level DEBUG
```

**Key distinction**:
- TUI progress verbosity is controlled by the subscription bootstrap level (not a config file).
- `--log-level` / `SOOTHE_LOG_LEVEL` controls **what gets written to CLI log file** (Python logging).

#### 3. Apply Configuration Changes

Restart daemon to pick up new config:

```bash
soothed stop
soothed start
```

CLI picks up `--log-level` / `SOOTHE_LOG_LEVEL` on every invocation, no restart needed.

---

## 📊 Understanding Verbosity Levels

Verbosity is a **client-side preference** that controls what progress events are displayed in the TUI. The daemon filters events before sending them over WebSocket (RFC-401, RFC-501).

| Verbosity Level | What You See in TUI | Use Case |
|-----------------|---------------------|----------|
| `quiet` | Only errors and final answers | Minimal distraction, production use |
| `normal` | Plan updates, tool summaries, subagent start/end | Default balanced view |
| `debug` | Protocol events, tool calls, **subagent internals**, step progress, thinking, heartbeats, internal state | Deep debugging |

**Example**: To see subagent internal reasoning and step-by-step progress, set `verbosity: debug`.

---

## 🔍 Diagnosing Issues with Logs

### 1. Monitor Daemon Backend Logs

Watch daemon execution logs in real-time:

```bash
tail -f ~/.soothe/logs/soothed.log
```

**What you'll see with DEBUG level**:
- Agent loop iteration details
- Protocol backend operations (planner, memory, durability)
- Tool invocations and responses
- Subagent delegation and results
- Verbose agent/loop messages (use Langfuse in `observability.langfuse` for full LLM traces)
- WebSocket message handling
- Goal execution DAG
- Checkpoint persistence

**Search for specific issues**:

```bash
# Find errors
grep -i "error\|exception\|failed" ~/.soothe/logs/soothed.log

# Find subagent issues
grep -i "subagent" ~/.soothe/logs/soothed.log

# Find specific tool issues
grep -i "tool.*browser\|tool.*wizsearch" ~/.soothe/logs/soothed.log

# Search daemon log for model-related lines (Langfuse UI for structured traces)
grep -i "chat model\|ainvoke\|token" ~/.soothe/logs/soothed.log
```

### 2. Monitor CLI Client Logs

Watch CLI connection and UI logs:

```bash
tail -f ~/.soothe/logs/soothe-cli.log
```

**What you'll see with DEBUG level**:
- WebSocket connection lifecycle
- Event stream processing
- TUI rendering details
- User input handling
- Command execution
- Error handling and recovery

**Search for connection issues**:

```bash
# Find WebSocket connection errors
grep -i "websocket\|connection\|timeout" ~/.soothe/logs/soothe-cli.log

# Find event handling errors
grep -i "event.*error\|event.*failed" ~/.soothe/logs/soothe-cli.log
```

### 3. Inspect Thread Conversation Logs

Thread logs provide audit trail for specific conversations:

```bash
# List thread directories
ls -la ~/.soothe/data/threads/

# Inspect specific thread logs
cat ~/.soothe/data/threads/{thread_id}/logs/conversation.jsonl

# Find issues in specific thread
grep -i "error\|exception" ~/.soothe/data/threads/{thread_id}/logs/conversation.jsonl

# Check thread metadata
cat ~/.soothe/data/threads/{thread_id}/manifest.json
```

**What thread logs contain**:
- Complete conversation history
- Goal progression
- Step execution details
- Tool call audit trail
- Subagent delegation records
- Timestamps for all events

---

## 🐛 Common Debugging Workflows

### Workflow 1: Debug Agent Behavior Issues

**Scenario**: Agent not executing expected steps, tools not being called, subagent delegation failing.

**Steps**:

1. Enable debug logging:
```bash
export SOOTHE_LOG_LEVEL=DEBUG
soothed stop
soothed start
```

2. Run agent with verbose TUI:
```bash
soothe -p "your query"
```

3. Monitor daemon logs in real-time:
```bash
tail -f ~/.soothe/logs/soothed.log
```

4. Look for:
- Agent loop iteration count
- Planner decisions (`RFC-304 PlannerProtocol`)
- Tool selection and execution
- Subagent delegation attempts
- Goal state transitions

### Workflow 2: Debug Model/LLM Issues

**Scenario**: Wrong model being used, malformed prompts, unexpected responses.

**Steps**:

1. Enable Langfuse in `~/.soothe/config/config.yml` under `observability.langfuse` (`enabled`, keys, optional `host`). Install `langfuse` if needed (`pip install langfuse`).

2. Restart daemon:
```bash
soothed stop
soothed start
```

3. Run query and check logs:
```bash
soothe -p "test query"
grep -i "langfuse\|observability" ~/.soothe/logs/soothed.log | tail -100
```

4. Inspect:
- Model resolution (`provider:model`)
- Prompt construction
- Tool definitions sent to LLM
- Response parsing
- Token usage statistics

### Workflow 2b: Debug daemon request timeout (goal killed mid-run)

**Symptoms**: `daemon.log` contains `request timeout (1209600s)` or `Request exceeded 1209600s timeout`; `soothe.log` shows `Step … cancelled`; no `goal_completed` in CLI.

**Steps**:

1. Confirm wall-clock duration matches configured cap:
```bash
rg 'request timeout|Request exceeded|cancelled after' ~/.soothe/logs/daemon.log ~/.soothe/data/loops/*/runner.log
```

2. Check active settings:
```bash
grep -A2 'request_timeout_seconds' ~/.soothe/config/daemon.yml
grep -A2 'goal_deadline_seconds' ~/.soothe/config/config.yml
```

Defaults (template): **1209600s (14 days)** for both daemon request timeout and autopilot goal deadline. Prior default was **7200s (2 hours)**.

3. Resume or re-run with a higher cap if the goal legitimately needs more wall-clock time (see [Troubleshooting — Request exceeded timeout](../troubleshooting/index.md#error-request-exceeded--timeout--step-cancelled-after-14-days)).

### Workflow 3: Debug Connection/Transport Issues

**Stale worker_pool subprocesses** (orphaned `multiprocessing.spawn` children after crashes or old daemon runs):

- **Automatic** (long-running daemon): enable `worker_pool` and `stale_worker_reap` in `daemon.yml` (`interval_seconds`, default 1800). The daemon reaps on start/stop and periodically while running; live pool workers are skipped.
- **Manual** (daemon stopped or one-off cleanup): `uv run python -m soothe_daemon.persistence` (add `--dry-run` to preview).
- **thread_pool mode**: periodic reap is not started (no spawn workers); startup/shutdown reap and the CLI remain harmless.

**Scenario**: CLI can't connect to daemon, WebSocket errors, timeout issues.

**Steps**:

1. Enable debug in both daemon and CLI:
```bash
export SOOTHE_LOG_LEVEL=DEBUG
soothed stop
soothed start
```

2. Check daemon WebSocket logs:
```bash
tail -f ~/.soothe/logs/soothed.log | grep -i "websocket\|transport\|connection"
```

3. Check CLI connection logs:
```bash
tail -f ~/.soothe/logs/soothe-cli.log | grep -i "websocket\|connection\|retry\|timeout"
```

4. Verify configuration:
```bash
# Check daemon WebSocket config (daemon.yml)
cat ~/.soothe/config/daemon.yml | grep -A 10 "websocket:"

# CLI connection uses --daemon-host / --daemon-port (defaults: 127.0.0.1:8765)
soothe --help | grep daemon
```

### Workflow 4: Debug Subagent Issues

**Scenario**: Explore, research, or an optional soothe-plugins delegate is not working; delegation failing.

**Steps**:

1. Enable debug logging:
```yaml
# ~/.soothe/config/config.yml
debug: true
logging:
  file:
    level: DEBUG
```

```bash
soothe --log-level DEBUG
```

2. Restart daemon:
```bash
soothed stop
soothed start
```

3. Test subagent:
```bash
soothe -p "browse example.com"
```

4. Monitor daemon logs for subagent:
```bash
tail -f ~/.soothe/logs/soothed.log | grep -i "subagent.*browser"
```

5. Look for:
- Subagent availability check
- Delegation envelope creation
- Subagent execution loop
- Result parsing
- Error handling

### Workflow 5: Debug Protocol Backend Issues

**Scenario**: Memory not working, planner failures, durability errors.

**Steps**:

1. Enable debug logging:
```bash
export SOOTHE_LOG_LEVEL=DEBUG
soothed stop
soothed start
```

2. Monitor protocol-specific logs:
```bash
# Memory protocol
tail -f ~/.soothe/logs/soothed.log | grep -i "memory.*protocol\|memory.*backend"

# Planner protocol
tail -f ~/.soothe/logs/soothed.log | grep -i "planner.*protocol\|planner.*backend"

# Durability protocol
tail -f ~/.soothe/logs/soothed.log | grep -i "durability.*protocol\|checkpoint"
```

3. Inspect backend configuration:
```bash
cat ~/.soothe/config/config.yml | grep -A 20 "protocols:"
```

---

## 🎯 Advanced Debugging

### LLM traces (Langfuse)

Configure `observability.langfuse` in daemon config and open the Langfuse UI for generations, spans, and costs. Daemon logs only reflect startup and errors for the integration; detailed prompts/responses live in Langfuse.

### Thread-Level Conversation Auditing

Enable thread-specific logs for conversation audit trails:

```yaml
logging:
  thread_logging:
    enabled: true
    dir: ""             # Empty = ~/.soothe/data/threads/{thread_id}/logs/
    retention_days: 30  # Auto-delete old threads
```

**Thread log structure**:
```
~/.soothe/data/threads/{thread_id}/
├── logs/
│   └── conversation.jsonl  # Full conversation history (JSONL format)
├── manifest.json           # Thread metadata (query, status, artifacts)
```

**Use cases**:
- Post-mortem analysis of failed conversations
- Audit trail for production agents
- Replay conversations for debugging
- Extract generated artifacts

### Performance Profiling with Logs

Analyze agent performance from logs:

```bash
# Optional: timing/token hints in logs (Langfuse UI is authoritative for LLM metrics)
grep -i "latency\|duration_ms\|token" ~/.soothe/logs/soothed.log | tail -50

# Find iteration counts
grep -i "iteration" ~/.soothe/logs/soothed.log | grep -i "max\|count"
```

---

## 📋 Debug Configuration Checklist

Complete checklist for maximum debug visibility:

### In `~/.soothe/config/config.yml`:

```yaml
# Global debug flag
debug: true

# Backend file logging
logging:
  file:
    level: DEBUG
  thread_logging:
    enabled: true
    retention_days: 30

# Langfuse (optional): observability.langfuse.enabled + keys in same file

# Performance tuning (optional, for debugging perf)
performance:
  enabled: true
  unified_classification: true
  classification_mode: llm
```

### CLI flags (optional):

```bash
soothe --log-level DEBUG          # CLI file logging
soothe --daemon-host 127.0.0.1 --daemon-port 8765
```

### Environment variables (optional):

```bash
export SOOTHE_DEBUG=true       # Global debug flag
export SOOTHE_LOG_LEVEL=DEBUG  # Override file logging levels
```

---

## 🛠️ Log Management

### Log Rotation

Soothe automatically rotates log files to prevent disk space issues:

**Daemon logs** (`soothed.log`):
- Max size: 5 MB (configurable via `logging.file.max_bytes`)
- Backup count: 3 files (configurable via `logging.file.backup_count`)
- Rotation: Automatic when file reaches max size

**CLI logs** (`soothe-cli.log`):
- Same rotation policy as daemon logs

**Thread logs** (`data/threads/{thread_id}/logs/conversation.jsonl`):
- Auto-deleted after `retention_days` (default: 30 days)
- Max size limit configurable via `logging.thread_logging.max_size_mb`

### Clearing Logs

```bash
# Clear daemon logs
rm ~/.soothe/logs/soothed.log*

# Clear CLI logs
rm ~/.soothe/logs/soothe-cli.log*

# Clear old thread logs (automatically done by retention policy)
find ~/.soothe/data/threads -mtime +30 -type d -exec rm -rf {} +

# Clear all logs (fresh start)
rm -rf ~/.soothe/logs/*
rm -rf ~/.soothe/data/threads/*
```

---

## 🔗 Related Documentation

- [Troubleshooting Guide](troubleshooting.md) - Common issues and solutions
- [Configuration Guide](configuration-guide/index.md) - Configuration reference
- [Daemon Management](daemon-management.md) - Daemon lifecycle
- [RFC-302](../specs/RFC-302-context-protocol-architecture.md) - Progress event protocol
- [RFC-401](../specs/RFC-401.md) - Event filtering and verbosity

---

## 💡 Tips

1. **Use environment variables for temporary debugging**: `SOOTHE_LOG_LEVEL=DEBUG` is faster than editing config files
2. **Match verbosity to your needs**: `debug` for understanding behavior and deep debugging
3. **Monitor logs in real-time**: `tail -f` gives immediate feedback during debugging
4. **Use grep to filter logs**: Focus on specific components (subagent, tool, protocol)
5. **Enable thread logging for audit trails**: Critical for production deployments
6. **Check LLM tracing for prompt issues**: Often the root cause of unexpected behavior
7. **Clear logs periodically**: Prevent disk space issues during long debug sessions