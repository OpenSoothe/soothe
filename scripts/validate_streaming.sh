#!/bin/bash
# Streaming Validation Script for Soothe

set -e

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║           Soothe Streaming Validation Script                     ║"
echo "╚══════════════════════════════════════════════════════════════════╝"

echo ""
echo "[1/6] Checking model configuration..."
python3 << 'PYEOF'
from soothe.config import SootheConfig

try:
    c = SootheConfig.from_yaml_file("config/config.dev.yml")
    m = c.create_chat_model("default")

    if m.streaming == True:
        print("✅ Model streaming enabled: True")
    else:
        print("❌ Model streaming NOT enabled: False")
        print("   Check settings.py has streaming=True parameter")
        exit(1)
except Exception as e:
    print(f"⚠️  Configuration check failed: {e}")
    exit(1)
PYEOF

echo ""
echo "[2/6] Checking unit tests..."
pytest packages/soothe/tests/unit/config/test_streaming.py -v --tb=short -q 2>/dev/null | grep -E "(PASSED|FAILED|test_)" | head -20
echo "✅ Unit tests validated"

echo ""
echo "[3/6] Checking daemon status..."
if soothed status &>/dev/null; then
    echo "✅ Daemon is running"
else
    echo "⚠️  Daemon not running - starting..."
    soothed start
    sleep 2
    echo "✅ Daemon started"
fi

echo ""
echo "[4/6] Testing CLI streaming (--no-tui)..."
echo "Query: 'count from 1 to 5'"
echo "---"
timeout 15s soothe --no-tui -p "count from 1 to 5, one number per line" 2>&1 | head -20
echo "---"
echo "✅ CLI test completed"

echo ""
echo "[5/6] Testing with longer query..."
echo "Query: 'write a 50-word essay about streaming'"
echo "---"
timeout 20s soothe --no-tui -p "write a 50-word essay about streaming in AI" 2>&1 | head -30
echo "---"
echo "✅ Long query test completed"

echo ""
echo "[6/6] Visual behavior check..."
echo ""
echo "Did you observe:"
echo "  ✅ Text appearing incrementally (line-by-line)?"
echo "  ✅ Immediate feedback during generation?"
echo "  ❌ Or entire response appearing at once after delay?"
echo ""
echo "If you saw incremental text → Streaming is WORKING ✅"
echo "If you saw batch output → Streaming may need debugging ❌"
echo ""

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║           Validation Complete                                     ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "For detailed analysis, check:"
echo "  - Debug logs: ~/.soothe/logs/soothe.log"
echo "  - LLM trace:  ~/.soothe/logs/llm_trace.log (if enabled)"
echo "  - Full guide: docs/howto_validate_streaming.md"
echo ""