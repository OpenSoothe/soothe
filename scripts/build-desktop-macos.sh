#!/usr/bin/env bash
#
# Build Soothe.app DMG for macOS (arm64).
#
# Prerequisites:
#   - Python >=3.11 with soothe packages installed (editable or wheel)
#   - Node.js >=20
#   - PyInstaller (added as dev dependency via `uv add --dev pyinstaller`)
#
# Usage:
#   ./scripts/build-desktop-macos.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Step 1: Build daemon binary with PyInstaller ==="
cd "$ROOT/packages/soothe-daemon"

uv run pyinstaller soothed.spec --noconfirm --clean

DAEMON_BIN="$ROOT/packages/soothe-daemon/dist/soothed/soothed"
if [ ! -f "$DAEMON_BIN" ]; then
  echo "ERROR: PyInstaller output not found at $DAEMON_BIN"
  exit 1
fi

DAEMON_SIZE=$(du -sh "$ROOT/packages/soothe-daemon/dist/soothed" | cut -f1)
echo "Daemon binary built: $DAEMON_SIZE"

echo ""
echo "=== Step 2: Build Electron app and package DMG ==="
cd "$ROOT/apps/soothe-desktop"
npm ci
npm run package:mac:bundled

echo ""
echo "=== Done ==="
echo "DMG files:"
ls -la "$ROOT/apps/soothe-desktop/release/"*.dmg 2>/dev/null || echo "(no DMG found — check release/ directory)"
