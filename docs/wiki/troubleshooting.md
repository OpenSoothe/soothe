# Troubleshooting Guide

Solutions to common issues with Soothe.

## API Key Issues

### Error: Could not resolve model

**Error**: `Could not resolve model openai:gpt-4o-mini`

**Solution**: Set your OpenAI API key:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

Or in `.env` file:

```bash
OPENAI_API_KEY=sk-your-key-here
```

### Error: Invalid API key

**Error**: `Invalid API key provided`

**Solution**:
1. Verify the key is correct
2. Check for typos or extra spaces
3. Ensure the key has necessary permissions
4. Try regenerating the key from the provider dashboard

## Subagent Issues

### Browser Agent Not Working

**Error**: `Browser subagent not available`

**Solution**: Install the browser extra:

```bash
pip install soothe[browser]
```

### Claude Agent Not Working

**Error**: `Claude subagent not available`

**Solution**:

1. Install the Claude extra:
```bash
pip install soothe[claude]
```

2. Set your Anthropic API key:
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### Subagent Disabled

**Error**: `Subagent 'browser' is disabled`

**Solution**: Enable in configuration:

```yaml
subagents:
  browser:
    enabled: true
```

## WebSocket Connection Issues

### Error: WebSocket connection failed

**Error**: `WebSocket connection failed` or `Connection refused`

**Solution**:

1. Check daemon status:
```bash
soothe-daemon status
```

2. Ensure WebSocket is enabled in config:
```yaml
daemon:
  transports:
    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
```

3. Restart daemon:
```bash
soothe-daemon stop
soothe-daemon start
```

### Error: Connection timeout

**Error**: `WebSocket connection timeout`

**Solution**:
1. Check firewall settings
2. Verify host and port are correct
3. Ensure no other process is using the port

## HTTP REST API Issues

### Error: Connection refused

**Error**: `Connection refused` when accessing REST API

**Solution**: Enable HTTP REST transport:

```yaml
daemon:
  transports:
    http_rest:
      enabled: true
      host: "127.0.0.1"
      port: 8766
```

Then restart daemon:

```bash
soothe-daemon stop
soothe-daemon start
```

### Error: 404 Not Found

**Error**: `404 Not Found` for API endpoint

**Solution**:
1. Check the endpoint URL is correct
2. Verify API version in path (`/api/v1/...`)
3. Visit http://localhost:8766/docs for API documentation

## Authentication Errors

### Error: Authentication failed

**Error**: `401 Unauthorized` or `Authentication required`

**Solution**:

Soothe does not include built-in authentication. If you're seeing auth errors, they're coming from your reverse proxy.

1. **Check reverse proxy configuration**: Ensure API key/JWT validation is configured correctly
2. **Verify credentials**: Check that you're sending the correct auth header
3. **Check reverse proxy logs**: Auth errors are logged by nginx/Caddy/Traefik, not Soothe

**Example with nginx**:
```nginx
# Check nginx error logs
tail -f /var/log/nginx/error.log

# Verify API key in request
curl -H "X-API-Key: your-api-key" \
  https://soothe.example.com/api/v1/threads
```

**Example with Caddy**:
```bash
# Check Caddy logs
journalctl -u caddy -f

# Verify JWT token
curl -H "Authorization: Bearer your-jwt-token" \
  https://soothe.example.com/api/v1/threads
```

### Error: CORS policy blocked

**Error**: `CORS policy blocked` in browser console

**Solution**: This is handled by the reverse proxy, not Soothe directly.

**nginx configuration**:
```nginx
location / {
    add_header Access-Control-Allow-Origin "https://your-app.example.com";
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS";
    add_header Access-Control-Allow-Headers "X-API-Key, Content-Type";

    if ($request_method = OPTIONS) {
        return 204;
    }

    proxy_pass http://localhost:8766;
}
```

**Caddy configuration**:
```
soothe.example.com {
    @websocket {
        header Connection *Upgrade*
        header Upgrade websocket
    }

    handle @websocket {
        reverse_proxy localhost:8765
    }

    handle /api/* {
        reverse_proxy localhost:8766
    }
}
```

## CORS Errors

### Error: CORS policy blocked

**Error**: `CORS policy blocked` in browser console

**Solution**: Add your origin to allowed CORS origins:

```yaml
daemon:
  transports:
    websocket:
      enabled: true
      cors_origins:
        - "http://localhost:*"
        - "http://127.0.0.1:*"
        - "http://myapp.example.com"  # Your origin
```

Restart daemon after updating:

```bash
soothe-daemon stop
soothe-daemon start
```

## Daemon Issues

### Error: Address already in use

**Error**: `Address already in use: ~/.soothe/soothe.sock`

**Solution**: Socket file exists from previous run

```bash
rm ~/.soothe/soothe.sock
soothe-daemon start
```

### Error: Daemon won't start

**Error**: Daemon exits immediately

**Solution**:

1. Check logs:
```bash
tail -f ~/.soothe/logs/daemon.log
```

2. Enable debug mode:
```bash
export SOOTHE_DEBUG=true
soothe-daemon start
```

3. Verify configuration:
```bash
soothe config validate
```

### Error: Daemon not responding

**Error**: Commands hang or timeout

**Solution**:

1. Check daemon status:
```bash
soothe-daemon status
```

2. Restart daemon:
```bash
soothe-daemon stop
soothe-daemon start
```

3. Check for zombie processes:
```bash
ps aux | grep soothe
kill -9 <pid>  # If needed
```

## Thread Issues

### Error: Thread not found

**Error**: `Thread abc123 not found`

**Solution**:

1. List available threads:
```bash
soothe thread list
```

2. Check thread ID spelling
3. Verify thread hasn't been deleted

### Error: Thread corrupted

**Error**: `Failed to load thread`

**Solution**:

1. Export thread data if possible:
```bash
soothe thread export abc123 --output backup.json
```

2. Delete and recreate:
```bash
soothe thread delete abc123
```

## Vector Store Issues

### Error: Connection refused (PostgreSQL)

**Error**: `Connection refused` for pgvector

**Solution**:

1. Start infrastructure:
```bash
docker compose up -d
```

2. Configure connection:
```yaml
vector_store_provider: pgvector
vector_store_config:
  dsn: "postgresql://postgres:postgres@localhost:5432/vectordb"
```

### Error: Collection not found

**Error**: `Collection 'soothe_skillify' not found`

**Solution**: Collections are created automatically on first use. Ensure the vector store is running and accessible.

## Model Resolution Issues

### Error: Provider not found

**Error**: `Provider 'openai' not found`

**Solution**: Ensure provider name matches:

```yaml
providers:
  - name: openai  # Must match router reference
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"

router:
  default: "openai:gpt-4o-mini"  # "openai" matches provider name
```

### Error: Model not found

**Error**: `Model 'gpt-4o-mini' not available`

**Solution**: Add model to provider list:

```yaml
providers:
  - name: openai
    models:
      - gpt-4o-mini  # Add here
      - gpt-4o
```

## Performance Issues

### Slow Response Times

**Solution**:

1. Check network latency
2. Use smaller model for simple tasks:
```yaml
router:
  fast: "openai:gpt-4o-mini"
```

3. Enable caching:
```yaml
prompt_caching: true
```

### High Memory Usage

**Solution**:

1. Reduce context size:
```yaml
context:
  max_tokens: 8000
```

2. Archive old threads:
```bash
soothe thread archive abc123
```

3. Restart daemon periodically

## Debug Mode

For comprehensive debugging instructions, see the [Debug Guide](../howto_debug.md).

Enable verbose logging to diagnose issues:

```bash
export SOOTHE_DEBUG=true
soothe
```

For daemon-specific logging:

```bash
export SOOTHE_DEBUG=true
soothe-daemon start
```

Or in YAML:

```yaml
debug: true
```

### Key Debug Features

The debug guide covers:

- **Log locations**: `~/.soothe/logs/`, `~/.soothe/runs/`
- **Enable debug logs**: Environment variables and config files
- **Monitor logs in real-time**: `tail -f` commands for daemon, CLI, and thread logs
- **LLM tracing**: Debug model behavior with request/response logging
- **Verbosity levels**: Understand TUI event filtering (quiet/normal/detailed/debug)
- **Common workflows**: Debug agent behavior, LLM issues, connection, subagents, protocols
- **Performance profiling**: Analyze agent performance from logs

## Getting Help

1. Use `/help` in the TUI to see available commands
2. Check the [Debug Guide](../howto_debug.md) for comprehensive debugging instructions
3. Check logs: `~/.soothe/logs/daemon.log`, `~/.soothe/logs/cli.log`
4. Review configuration: `soothe config show`
5. Check the [documentation](../) for detailed guides
6. Review RFCs and implementation guides in `docs/specs/` and `docs/impl/`

## Related Guides

- [Debug Guide](../howto_debug.md) - Enable debug logs, diagnose issues, log locations
- [Configuration Guide](configuration.md) - Configuration reference
- [Daemon Management](daemon-management.md) - Daemon lifecycle
- [Multi-Transport Setup](multi-transport.md) - Transport configuration
- [Authentication](authentication.md) - Auth setup