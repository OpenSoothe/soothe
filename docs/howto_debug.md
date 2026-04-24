# Soothe Debug Guide

Comprehensive guide for debugging Soothe agents and diagnosing issues.

---

## 📁 Log Locations

Soothe maintains multiple log files in `~/.soothe/` for different purposes:

### Main Log Files

| Log File | Purpose | Configured By |
|----------|---------|---------------|
| `~/.soothe/logs/soothe-daemon.log` | Daemon backend logs (agent execution, protocols, tools) | `config.yml` → `logging.file.level` |
| `~/.soothe/logs/soothe-cli.log` | CLI client logs (connection, UI, event handling) | `cli_config.yml` → `logging_level` |

### Data Directory Structure

All runtime data is stored in `~/.soothe/data/`:

| Directory/File | Purpose | Configured By |
|----------------|---------|---------------|
| `~/.soothe/data/threads/{thread_id}/logs/conversation.jsonl` | Thread-specific conversation audit logs | `config.yml` → `logging.thread_logging` |
| `~/.soothe/data/threads/{thread_id}/manifest.json` | Thread metadata (query, status, artifacts) | Automatic |
| `~/.soothe/data/langgraph_checkpoints.db` | LangGraph checkpoint database | `config.yml` → `durability.checkpointer` |
| `~/.soothe/data/metadata.db` | Metadata database | `config.yml` → `persistence.default_backend` |
| `~/.soothe/data/history.jsonl` | History log | Automatic |
| `~/.soothe/data/loops/{loop_id}/` | Agent loop checkpoints | Automatic |

**Note**: Thread logs are only created when `logging.thread_logging.enabled: true`.

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
soothe-daemon stop
soothe-daemon start
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
    path: ""            # Empty = ~/.soothe/logs/soothe-daemon.log
    max_bytes: 5242880  # 5 MB before rotation
    backup_count: 3     # Number of rotating backups

  # Thread conversation logging (audit trail for each conversation)
  thread_logging:
    enabled: true       # Enable thread-specific logs
    dir: ""             # Empty = ~/.soothe/data/threads/{thread_id}/logs/
    retention_days: 30  # Auto-delete old threads

# LLM request/response tracing (for debugging model behavior)
llm_tracing:
  enabled: true         # Enable LLM tracing middleware
  log_preview_length: 1000  # Max chars to log for message previews (50-1000)
```

#### 2. Enable CLI Client Debug Logs

Edit `~/.soothe/config/cli_config.yml`:

```yaml
# Client verbosity controls what events are DISPLAYED in TUI/CLI
# This is a CLIENT-side preference, sent to daemon when subscribing to threads
# Daemon filters events per-client before sending over WebSocket (RFC-401, RFC-501)
#
# Options:
#   - quiet: Only errors and final answers
#   - normal: Plan updates, tool summaries, subagent start/end (default)
#   - detailed: Protocol events, tool calls, SUBAGENT INTERNALS/STEP PROGRESS
#   - debug: Everything including thinking, heartbeats
verbosity: debug

# Python logging level for ~/.soothe/logs/soothe-cli.log only (does not change TUI
# progress verbosity above). When omitted, level follows verbosity.
# SOOTHE_LOG_LEVEL overrides this setting.
logging_level: DEBUG
```

**Key distinction**:
- `verbosity` controls **what you SEE in TUI** (event filtering)
- `logging_level` controls **what gets written to CLI log file** (Python logging)

#### 3. Apply Configuration Changes

Restart daemon to pick up new config:

```bash
soothe-daemon stop
soothe-daemon start
```

CLI picks up `cli_config.yml` on every invocation, no restart needed.

---

## 📊 Understanding Verbosity Levels

Verbosity is a **client-side preference** that controls what progress events are displayed in the TUI. The daemon filters events before sending them over WebSocket (RFC-401, RFC-501).

| Verbosity Level | What You See in TUI | Use Case |
|-----------------|---------------------|----------|
| `quiet` | Only errors and final answers | Minimal distraction, production use |
| `normal` | Plan updates, tool summaries, subagent start/end | Default balanced view |
| `detailed` | Protocol events, tool calls, **subagent internals**, step progress | Understanding agent behavior |
| `debug` | Everything including thinking, heartbeats, internal state | Deep debugging |

**Example**: To see subagent internal reasoning and step-by-step progress, set `verbosity: detailed` or `verbosity: debug`.

---

## 🔍 Diagnosing Issues with Logs

### 1. Monitor Daemon Backend Logs

Watch daemon execution logs in real-time:

```bash
tail -f ~/.soothe/logs/soothe-daemon.log
```

**What you'll see with DEBUG level**:
- Agent loop iteration details
- Protocol backend operations (planner, memory, durability)
- Tool invocations and responses
- Subagent delegation and results
- LLM prompts and responses (with `llm_tracing.enabled: true`)
- WebSocket message handling
- Goal execution DAG
- Checkpoint persistence

**Search for specific issues**:

```bash
# Find errors
grep -i "error\|exception\|failed" ~/.soothe/logs/soothe-daemon.log

# Find subagent issues
grep -i "subagent" ~/.soothe/logs/soothe-daemon.log

# Find specific tool issues
grep -i "tool.*browser\|tool.*wizsearch" ~/.soothe/logs/soothe-daemon.log

# Find LLM tracing (requires llm_tracing.enabled: true)
grep -i "llm_tracing\|prompt\|response" ~/.soothe/logs/soothe-daemon.log
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
soothe-daemon stop
soothe-daemon start
```

2. Run agent with verbose TUI:
```bash
# Edit ~/.soothe/config/cli_config.yml
verbosity: detailed

# Run agent
soothe "your query"
```

3. Monitor daemon logs in real-time:
```bash
tail -f ~/.soothe/logs/soothe-daemon.log
```

4. Look for:
- Agent loop iteration count
- Planner decisions (`RFC-200 PlannerProtocol`)
- Tool selection and execution
- Subagent delegation attempts
- Goal state transitions

### Workflow 2: Debug Model/LLM Issues

**Scenario**: Wrong model being used, malformed prompts, unexpected responses.

**Steps**:

1. Enable LLM tracing in `~/.soothe/config/config.yml`:
```yaml
llm_tracing:
  enabled: true
  log_preview_length: 1000  # See full prompts/responses
```

2. Restart daemon:
```bash
soothe-daemon stop
soothe-daemon start
```

3. Run query and check logs:
```bash
soothe "test query"
grep -i "llm_tracing\|prompt\|response" ~/.soothe/logs/soothe-daemon.log | tail -100
```

4. Inspect:
- Model resolution (`provider:model`)
- Prompt construction
- Tool definitions sent to LLM
- Response parsing
- Token usage statistics

### Workflow 3: Debug Connection/Transport Issues

**Scenario**: CLI can't connect to daemon, WebSocket errors, timeout issues.

**Steps**:

1. Enable debug in both daemon and CLI:
```bash
export SOOTHE_LOG_LEVEL=DEBUG
soothe-daemon stop
soothe-daemon start
```

2. Check daemon WebSocket logs:
```bash
tail -f ~/.soothe/logs/soothe-daemon.log | grep -i "websocket\|transport\|connection"
```

3. Check CLI connection logs:
```bash
tail -f ~/.soothe/logs/soothe-cli.log | grep -i "websocket\|connection\|retry\|timeout"
```

4. Verify configuration:
```bash
# Check daemon WebSocket config
cat ~/.soothe/config/config.yml | grep -A 10 "websocket:"

# Check CLI connection config
cat ~/.soothe/config/cli_config.yml | grep -A 10 "websocket:"
```

### Workflow 4: Debug Subagent Issues

**Scenario**: Browser/Claude/Explore subagent not working, delegation failing.

**Steps**:

1. Enable debug logging and verbose TUI:
```yaml
# ~/.soothe/config/config.yml
debug: true
logging:
  file:
    level: DEBUG

# ~/.soothe/config/cli_config.yml
verbosity: detailed  # See subagent internals
```

2. Restart daemon:
```bash
soothe-daemon stop
soothe-daemon start
```

3. Test subagent:
```bash
soothe "browse example.com"
```

4. Monitor daemon logs for subagent:
```bash
tail -f ~/.soothe/logs/soothe-daemon.log | grep -i "subagent.*browser"
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
soothe-daemon stop
soothe-daemon start
```

2. Monitor protocol-specific logs:
```bash
# Memory protocol
tail -f ~/.soothe/logs/soothe-daemon.log | grep -i "memory.*protocol\|memory.*backend"

# Planner protocol
tail -f ~/.soothe/logs/soothe-daemon.log | grep -i "planner.*protocol\|planner.*backend"

# Durability protocol
tail -f ~/.soothe/logs/soothe-daemon.log | grep -i "durability.*protocol\|checkpoint"
```

3. Inspect backend configuration:
```bash
cat ~/.soothe/config/config.yml | grep -A 20 "protocols:"
```

---

## 🎯 Advanced Debugging

### LLM Request/Response Tracing

Enable comprehensive LLM tracing to debug model behavior:

```yaml
llm_tracing:
  enabled: true
  log_preview_length: 1000  # Max chars for message previews (50-1000)
```

**What gets logged**:
- Full system prompt
- User message
- Tool definitions
- Model response (parsed)
- Token usage (prompt + completion)
- Latency metrics
- Cache hit/miss status

**Example output in daemon log**:
```
[LLM Tracing] Request to openai:gpt-4o-mini
  Prompt preview: "You are a helpful AI assistant..." (truncated to 1000 chars)
  Tools: browser, wizsearch, explore
  Temperature: 0.7

[LLM Tracing] Response from openai:gpt-4o-mini
  Content: "I'll help you with that..."
  Tool calls: browser(query="...")
  Token usage: prompt=500, completion=150, total=650
  Latency: 1.2s
```

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
# Find slow LLM calls (requires llm_tracing.enabled: true)
grep -i "latency:" ~/.soothe/logs/soothe-daemon.log | awk '{print $NF}' | sort -n

# Find token usage patterns
grep -i "token usage:" ~/.soothe/logs/soothe-daemon.log | awk -F'total=' '{print $2}' | sort -n

# Find iteration counts
grep -i "iteration" ~/.soothe/logs/soothe-daemon.log | grep -i "max\|count"
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

# LLM tracing
llm_tracing:
  enabled: true
  log_preview_length: 1000

# Performance tuning (optional, for debugging perf)
performance:
  enabled: true
  unified_classification: true
  classification_mode: llm
```

### In `~/.soothe/config/cli_config.yml`:

```yaml
# Client verbosity (TUI event display)
verbosity: detailed  # or debug

# Client file logging
logging_level: DEBUG
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

**Daemon logs** (`soothe-daemon.log`):
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
rm ~/.soothe/logs/soothe-daemon.log*

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

- [Troubleshooting Guide](wiki/troubleshooting.md) - Common issues and solutions
- [Configuration Guide](wiki/configuration.md) - Configuration reference
- [Daemon Management](wiki/daemon-management.md) - Daemon lifecycle
- [RFC-400](specs/RFC-400-context-protocol-architecture.md) - Progress event protocol
- [RFC-401](specs/RFC-401.md) - Event filtering and verbosity

---

## 💡 Tips

1. **Use environment variables for temporary debugging**: `SOOTHE_LOG_LEVEL=DEBUG` is faster than editing config files
2. **Match verbosity to your needs**: `detailed` for understanding behavior, `debug` for deep debugging
3. **Monitor logs in real-time**: `tail -f` gives immediate feedback during debugging
4. **Use grep to filter logs**: Focus on specific components (subagent, tool, protocol)
5. **Enable thread logging for audit trails**: Critical for production deployments
6. **Check LLM tracing for prompt issues**: Often the root cause of unexpected behavior
7. **Clear logs periodically**: Prevent disk space issues during long debug sessions