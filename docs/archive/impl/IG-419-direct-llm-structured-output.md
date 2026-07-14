# IG-419: Structured `direct_llm` output

Wire optional JSON Schema on `loop_input` for daemon `intent_hint=direct_llm` turns.

## Wire fields

| Field | Type | Notes |
|-------|------|-------|
| `response_schema` | object | Client JSON Schema (must include `"type"`) |
| `response_schema_name` | string | Optional provider schema name |
| `response_schema_strict` | bool | Default `true` when schema is set |

## Client examples

**Go** (`soothe-client-go`):

```go
schema := map[string]interface{}{
    "type": "object",
    "properties": map[string]interface{}{"title": map[string]interface{}{"type": "string"}},
    "required": []interface{}{"title"},
    "additionalProperties": false,
}
client.SendInput(ctx, prompt,
    soothe.WithLoopID(loopID),
    soothe.WithIntentHint("direct_llm"),
    soothe.WithResponseSchema(schema),
    soothe.WithResponseSchemaName("WorkspaceTitle"),
)
```

**Python SDK**:

```python
await client.send_input(
    loop_id,
    prompt,
    intent_hint="direct_llm",
    response_schema={...},
)
```

Assistant `content` is a JSON string when `response_schema` is set.

## Integration tests

Run with API keys and `--run-integration`:

| Area | Path |
|------|------|
| Soothe core | `packages/soothe/tests/integration/utils/llm/test_structured_direct_llm_integration.py` |
| Daemon | `packages/soothe-daemon/tests/integration/daemon/test_direct_llm_structured.py` |
| Go client | `client/go/integration_direct_llm_test.go` (`TestIntegration_IntentHintDirectLLMStructured*`) |

Go integration tests require a running daemon at `ws://localhost:8765` (same as other `client/go/integration_*` tests).
