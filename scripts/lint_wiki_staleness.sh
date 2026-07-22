#!/bin/bash
# lint_wiki_staleness.sh
#
# Purpose: Detect stale references in docs/wiki/**/*.md that are known to have
# been removed or renamed in the codebase. This script prevents regression by
# failing CI when phantom subagents, wrong class names, deprecated CLI commands,
# stale paths, or nonexistent RFC numbers are introduced.
#
# Exclusions:
#   - changelog.md: Documents historical state; old names/paths are expected.
#   - archive/:    Archived historical docs; references are intentionally stale.
#   - .backups/:   Auto-generated backup files; not user-facing.
#
# Usage: ./scripts/lint_wiki_staleness.sh
# Exit code: 0 if no issues found, 1 if any stale patterns detected

set -uo pipefail

WIKI_DIR="docs/wiki"
ERRORS=0

# Files/dirs that legitimately contain historical references and are excluded
# from all checks. grep filters through these via invert-match (-v).
#   - changelog.md: Documents historical state; old names/paths are expected.
#   - archive/:    Archived historical docs; references are intentionally stale.
#   - .backups/:   Auto-generated backup files from surgical edits; not user-facing.
EXCLUDE_FILTER="changelog.md\|archive/\|\.backups/"

echo "=== Wiki Staleness Lint ==="
echo "Scanning $WIKI_DIR/**/*.md for known stale patterns..."
echo "Excluding: changelog.md, archive/, .backups/"
echo ""

# ---------------------------------------------------------------------------
# Pattern 1: 'explore' as a subagent name (phantom — removed per cleanup)
# ---------------------------------------------------------------------------
echo "[1/7] Checking for phantom 'explore' subagent references..."
OUTPUT=$(grep -rn --include="*.md" -E "subagent.*explore|explore.*subagent|\"explore\"|'explore'" "$WIKI_DIR" 2>/dev/null | grep -v "$EXCLUDE_FILTER" || true)
if [ -n "$OUTPUT" ]; then
    echo "  ERROR: Found 'explore' referenced as a subagent"
    echo "$OUTPUT" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
else
    echo "  OK"
fi

# ---------------------------------------------------------------------------
# Pattern 2: 'WeaviateStore' without 'Vector' (should be WeaviateVectorStore)
# ---------------------------------------------------------------------------
echo "[2/7] Checking for 'WeaviateStore' (should be 'WeaviateVectorStore')..."
OUTPUT=$(grep -rn --include="*.md" "WeaviateStore" "$WIKI_DIR" 2>/dev/null | grep -v "WeaviateVectorStore" | grep -v "$EXCLUDE_FILTER" || true)
if [ -n "$OUTPUT" ]; then
    echo "  ERROR: Found 'WeaviateStore' - use 'WeaviateVectorStore' instead"
    echo "$OUTPUT" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
else
    echo "  OK"
fi

# ---------------------------------------------------------------------------
# Pattern 3: Deprecated CLI commands (config init/show/validate)
# ---------------------------------------------------------------------------
echo "[3/7] Checking for deprecated CLI commands (config init/show/validate)..."
OUTPUT=$(grep -rn --include="*.md" -E "soothe config init|soothe config show|soothe config validate" "$WIKI_DIR" 2>/dev/null | grep -v "$EXCLUDE_FILTER" || true)
if [ -n "$OUTPUT" ]; then
    echo "  ERROR: Found deprecated CLI commands (config init/show/validate)"
    echo "$OUTPUT" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
else
    echo "  OK"
fi

# ---------------------------------------------------------------------------
# Pattern 4: Stale paths 'core/strange_loop/' (should be 'sloop/engine/')
# ---------------------------------------------------------------------------
echo "[4/7] Checking for stale 'core/strange_loop/' paths..."
OUTPUT=$(grep -rn --include="*.md" "core/strange_loop/" "$WIKI_DIR" 2>/dev/null | grep -v "$EXCLUDE_FILTER" || true)
if [ -n "$OUTPUT" ]; then
    echo "  ERROR: Found stale path 'core/strange_loop/' - use 'sloop/engine/' instead"
    echo "$OUTPUT" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
else
    echo "  OK"
fi

# ---------------------------------------------------------------------------
# Pattern 5: Stale event names 'soothe.iteration.' (should be 'soothe.cognition.strange_loop.')
# ---------------------------------------------------------------------------
echo "[5/7] Checking for stale event names 'soothe.iteration.'..."
OUTPUT=$(grep -rn --include="*.md" "soothe\.iteration\." "$WIKI_DIR" 2>/dev/null | grep -v "$EXCLUDE_FILTER" || true)
if [ -n "$OUTPUT" ]; then
    echo "  ERROR: Found stale event prefix 'soothe.iteration.' - use 'soothe.cognition.strange_loop.' instead"
    echo "$OUTPUT" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
else
    echo "  OK"
fi

# ---------------------------------------------------------------------------
# Pattern 6: Nonexistent daemon methods (wait_ready, status)
# ---------------------------------------------------------------------------
echo "[6/7] Checking for nonexistent daemon methods (wait_ready, status)..."
OUTPUT=$(grep -rn --include="*.md" -E "daemon\.wait_ready|wait_ready\(\)" "$WIKI_DIR" 2>/dev/null | grep -v "$EXCLUDE_FILTER" || true)
if [ -n "$OUTPUT" ]; then
    echo "  ERROR: Found nonexistent method 'wait_ready()' on daemon"
    echo "$OUTPUT" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
fi
OUTPUT=$(grep -rn --include="*.md" -E "\.status\(\)" "$WIKI_DIR" 2>/dev/null | grep -v "health" | grep -v "get_status" | grep -v "$EXCLUDE_FILTER" || true)
if [ -n "$OUTPUT" ]; then
    echo "  ERROR: Found nonexistent method 'status()' on daemon (use 'health' or specific status methods)"
    echo "$OUTPUT" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
else
    echo "  OK"
fi

# ---------------------------------------------------------------------------
# Pattern 7: Phantom RFC numbers (611, 612, 0008, 0010, 0013, 0015)
# ---------------------------------------------------------------------------
echo "[7/7] Checking for phantom RFC numbers (611, 612, 0008, 0010, 0013, 0015)..."
PHANTOM_RFCS="611 612 0008 0010 0013 0015"
PHANTOM_FOUND=0
for rfc in $PHANTOM_RFCS; do
    OUTPUT=$(grep -rn --include="*.md" -E "RFC-0*$rfc|rfc-0*$rfc" "$WIKI_DIR" 2>/dev/null | grep -v "$EXCLUDE_FILTER" || true)
    if [ -n "$OUTPUT" ]; then
        echo "  ERROR: Found phantom RFC number RFC-$rfc (does not exist)"
        echo "$OUTPUT" | sed 's/^/    /'
        PHANTOM_FOUND=1
    fi
done
if [ "$PHANTOM_FOUND" -eq 0 ]; then
    echo "  OK"
else
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [ "$ERRORS" -eq 0 ]; then
    echo "=== SUCCESS: No stale patterns found ==="
    exit 0
else
    echo "=== FAILURE: Found $ERRORS stale pattern categories ==="
    exit 1
fi
