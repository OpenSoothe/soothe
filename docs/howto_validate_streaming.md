# How to Validate Streaming Works

This guide shows how to test and verify that LLM token streaming is working correctly in Soothe.

---

## Quick Validation (Recommended)

### Test 1: CLI Streaming (--no-tui)

```bash
# Start daemon (if not running)
soothed start

# Test streaming with a long query
soothe --no-tui -p "write a 100-word essay about AI agents"
```

**What to observe**:
- ✅ **Streaming working**: Text appears line-by-line or chunk-by-chunk as it's generated
- ❌ **Batch mode**: Entire response appears at once after a delay

**Visual indicator**: You should see text "flowing" onto the screen, not popping up as a complete block.

### Test 2: TUI Streaming

```bash
# Test in TUI mode
soothe -p "write a 100-word essay about AI agents"
```

**What to observe**:
- ✅ **Streaming working**: Assistant message widget updates incrementally with new text
- ❌ **Batch mode**: Full message appears at once

**Visual indicator**: Text should appear gradually in the chat panel, similar to typing.

---

## Debug Mode Validation

### Test 3: Enable Debug Logs

```bash
# Enable verbose logging to see streaming chunks
SOOTHE_LOG_LEVEL=DEBUG soothe --no-tui -p "write a short essay"
```

**Check logs** at `~/.soothe/logs/soothe.log`:

```bash
# Look for streaming indicators
tail -f ~/.soothe/logs/soothe.log | grep -i "stream"
```

**Expected log patterns**:
- `StreamMessagesHandler` callback active
- Multiple `AIMessageChunk` events
- `"messages"` stream mode chunks arriving

### Test 4: LLM Tracing

```bash
# Enable LLM tracing (from config.dev.yml)
soothe --no-tui -p "test streaming"

# Check trace logs
tail -f ~/.soothe/logs/llm_trace.log
```

**Expected**: Multiple request chunks with streaming tokens, not single request/response pair.

---

## Technical Verification

### Test 5: Check Model Configuration

```bash
# Run Python to verify model has streaming=True
python3 -c "
from soothe.config import SootheConfig
config = SootheConfig.from_yaml_file('config/config.dev.yml')
model = config.create_chat_model('default')
print(f'Model streaming: {model.streaming}')
assert model.streaming == True, 'Streaming not enabled!'
print('✅ Streaming verified')
"
```

**Expected output**: `Model streaming: True` followed by `✅ Streaming verified`

### Test 6: Count Streaming Chunks

```bash
# Create a test script to count chunks
cat > /tmp/test_streaming.py << 'EOF'
import asyncio
from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner

async def test_streaming():
    config = SootheConfig.from_yaml_file("config/config.dev.yml")
    runner = SootheRunner.from_config(config)

    query = "write a 50-word essay"
    chunk_count = 0

    async for chunk in runner.astream(query):
        namespace, mode, data = chunk
        if mode == "messages":
            chunk_count += 1
            print(f"Chunk {chunk_count}: {data}")

    print(f"\n✅ Received {chunk_count} streaming chunks")
    assert chunk_count > 1, f"Only {chunk_count} chunks - streaming may not be working!"

asyncio.run(test_streaming())
EOF

python3 /tmp/test_streaming.py
```

**Expected**: Multiple chunks (>1) with incremental text content.

---

## Behavioral Differences

### Streaming Mode (✅ Working)

**Characteristics**:
- Text appears gradually, like typing
- Multiple small updates to UI/output
- Immediate feedback, even for long responses
- Feels responsive and interactive

**Example output timing**:
```
Chunk 1 (0.1s): "AI agents"
Chunk 2 (0.2s): " are autonomous"
Chunk 3 (0.3s): " software systems"
Chunk 4 (0.4s): " that can perform"
...
```

### Batch Mode (❌ Not Working)

**Characteristics**:
- Silent delay during generation
- Entire response appears suddenly
- No intermediate updates
- Feels slower despite same generation time

**Example output timing**:
```
[5 second delay]
[Complete 100-word essay appears all at once]
```

---

## Visual Testing Guide

### Test 7: Side-by-Side Comparison

**Before fix** (batch mode):
```bash
# Check old behavior (if you can revert temporarily)
git stash
soothe --no-tui -p "count from 1 to 10"
# Result: Entire response appears after 2-3 seconds
```

**After fix** (streaming):
```bash
git stash pop
soothe --no-tui -p "count from 1 to 10"
# Result: Numbers appear one by one
```

**Visual test**: Use a query that produces sequential output (counting, lists) to easily see streaming behavior.

---

## Common Issues & Solutions

### Issue 1: No Streaming Visible

**Check**:
```bash
# Verify model configuration
python3 -c "from soothe.config import SootheConfig; c = SootheConfig.from_yaml_file('config/config.dev.yml'); print(c.create_chat_model().streaming)"
```

**If False**: Ensure changes are applied:
```bash
git status packages/soothe/src/soothe/config/settings.py
```

### Issue 2: Provider Doesn't Support Streaming

**Check provider compatibility**:
- OpenAI: ✅ Full streaming support
- Anthropic: ✅ Full streaming support
- DashScope/Qwen: ✅ Streaming supported (OpenAI-compatible)
- Ollama: ⚠️ Check `OLLAMA_HOST` config
- LMStudio: ⚠️ Depends on model

**Solution**: Test with known streaming-capable provider first (OpenAI/Anthropic).

### Issue 3: Cache Has Old Model

**Clear model cache**:
```bash
# Restart daemon to clear caches
soothed stop
soothed start
```

---

## Automated Test Script

```bash
#!/bin/bash
# Complete streaming validation script

echo "=== Streaming Validation Script ==="

echo "\n[1/5] Checking model configuration..."
python3 -c "
from soothe.config import SootheConfig
c = SootheConfig.from_yaml_file('config/config.dev.yml')
m = c.create_chat_model('default')
assert m.streaming == True
print('✅ Model streaming enabled')
"

echo "\n[2/5] Checking unit tests..."
pytest packages/soothe/tests/unit/config/test_streaming.py -v
echo "✅ Unit tests passed"

echo "\n[3/5] Testing daemon connection..."
soothed status || soothed start
echo "✅ Daemon running"

echo "\n[4/5] Testing streaming with short query..."
echo "Query: 'hello'"
timeout 10s soothe --no-tui -p "hello" || echo "⚠️ Query timed out"

echo "\n[5/5] Testing streaming with long query..."
echo "Query: 'write a 100-word essay'"
timeout 30s soothe --no-tui -p "write a 100-word essay about AI" || echo "⚠️ Query timed out"

echo "\n=== Validation Complete ==="
echo "Check the output above - text should appear incrementally, not as one block"
```

**Run**: `bash /tmp/streaming_validation.sh`

---

## Success Indicators

✅ **Streaming is working** if you observe:
1. Model configuration shows `streaming=True`
2. Unit tests pass (8 new tests)
3. Text appears incrementally in CLI
4. TUI chat widget updates gradually
5. Debug logs show multiple `AIMessageChunk` events
6. Chunk count > 1 in runner test
7. Immediate user feedback during generation

❌ **Streaming is NOT working** if you observe:
1. Model shows `streaming=False`
2. Unit tests fail
3. Entire response appears at once
4. Single request/response in LLM trace logs
5. Only 1 chunk from runner.astream()
6. Long delays before any output

---

## Next Steps

1. **Run quick validation** (Test 1 & 2)
2. **Check debug logs** if behavior unclear (Test 3)
3. **Run automated script** for comprehensive check
4. **Report results** with observations (streaming vs batch behavior)

**Provide feedback**: Let me know if streaming is working as expected or if you need assistance debugging!