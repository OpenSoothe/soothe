# LLM Request/Response Tracing

The `LLMTracingMiddleware` provides comprehensive debugging information for LLM request/response lifecycle.

## Overview

This middleware traces every LLM call and logs detailed debug information including:
- **Request details**: message count, total length, system prompt preview
- **Response details**: token usage, latency, response preview
- **Request/response correlation**: unique trace IDs for matching requests to responses

## Enabling LLM Tracing

LLM tracing is enabled in two ways:

### 1. Environment Variable (Recommended for Debugging)

Set `SOOTHE_LOG_LEVEL=DEBUG` to enable LLM tracing:

```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "your query"
```

### 2. Configuration File

Add to your `config.yml`:

```yaml
llm_tracing:
  enabled: true
```

## Log Output Examples

### Request Logging

```
[LLM Trace #1] Request: 3 messages (1.2K chars)
[LLM Trace #1] Messages: system=1, human=1, ai=1
[LLM Trace #1] System prompt (preview): You are a helpful assistant specialized in code analysis...
[LLM Trace #1] Thread: thread-123
```

### Response Logging

```
[LLM Trace #1] Response: 340ms, preview: Here's the analysis of your code...
[LLM Trace #1] Token usage: prompt=256, completion=128, total=384
```

### Error Logging

```
[LLM Trace #2] Error after 1200ms: RateLimitError: Rate limit exceeded
```

## Use Cases

### Debugging Prompt Construction

Trace what prompts are being sent to the LLM:

```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "analyze this file" 2>&1 | grep "LLM Trace"
```

### Analyzing Token Usage

Monitor token consumption across requests:

```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "complex query" 2>&1 | grep "Token usage"
```

### Profiling LLM Latency

Measure LLM response times:

```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "query" 2>&1 | grep "Response:"
```

### Understanding Tool Calls

See when the LLM makes tool calls:

```
[LLM Trace #3] Tool calls: 2 (read_file, run_command)
```

## Configuration Options

The middleware accepts the following parameters:

- `log_preview_length`: Maximum characters to log for message previews (default: 200)

Example with custom preview length:

```python
from soothe.core.middleware import LLMTracingMiddleware

middleware = LLMTracingMiddleware(log_preview_length=500)
```

## Middleware Stack Position

LLM tracing middleware is positioned after system prompt optimization in the middleware stack:

1. Policy enforcement
2. System prompt optimization
3. **LLM tracing** ← Traces after prompt optimization
4. Execution hints
5. Workspace context
6. Subagent context

This ensures you see the final prompts after all modifications.

## Log Format

All logs follow this pattern:

```
[LLM Trace #<id>] <message_type>: <details>
```

Where:
- `<id>`: Unique sequential trace ID
- `<message_type>`: Request, Response, Error, etc.
- `<details>`: Specific information

## Performance Impact

The middleware has minimal overhead:
- In-memory trace ID counter
- Lightweight message counting
- Only active when `SOOTHE_LOG_LEVEL=DEBUG` or explicitly enabled

## Integration with Existing Logging

LLM tracing works alongside existing Soothe logging:

```bash
# Enable all debug logging including LLM traces
SOOTHE_LOG_LEVEL=DEBUG soothe "query"

# Filter to see only LLM traces
SOOTHE_LOG_LEVEL=DEBUG soothe "query" 2>&1 | grep "\[LLM Trace"
```

## Related Documentation

- [System Prompt Optimization](./specs/RFC-0012-performance-optimization.md)
- [Middleware Architecture](./specs/RFC-0001-core-modules-architecture.md)
- [Debugging Guide](./user_guide.md#debugging)