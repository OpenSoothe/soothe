#!/usr/bin/env bash
# End-to-end cron test against a live soothe daemon.
#
# Usage:
#   ./scripts/test_cron_e2e.sh
#
# Requires: soothed running, LLM configured for NL extraction.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 1
fi

echo "==> Checking daemon"
if uv run soothed status 2>&1 | grep -q "stopped"; then
  echo "Starting daemon..."
  uv run soothed start
fi
uv run soothed status

JOB_TEXT="in 10 minutes e2e cron script verification task"
CANCEL_TEXT="tomorrow at 3pm e2e cron script cancel target"

echo "==> soothe cron add"
ADD_OUT="$(uv run soothe cron add "$JOB_TEXT" 2>&1)"
echo "$ADD_OUT"
JOB_ID="$(echo "$ADD_OUT" | grep -Eo 'ID:[[:space:]]+[a-f0-9]+' | awk '{print $2}' | head -1)"
if [[ -z "$JOB_ID" ]]; then
  echo "Failed to parse job id from add output" >&2
  exit 1
fi

echo "==> soothe -p '/cron ...' (headless)"
HEADLESS_OUT="$(uv run soothe -p "/cron in 15 minutes e2e headless cron path" --no-tui 2>&1)"
echo "$HEADLESS_OUT"
HEADLESS_ID="$(echo "$HEADLESS_OUT" | grep -Eo 'Scheduled cron job: [a-f0-9]+' | awk '{print $4}')"
if [[ -z "$HEADLESS_ID" ]]; then
  echo "Failed to parse job id from headless output" >&2
  exit 1
fi

echo "==> soothe cron list --status pending"
uv run soothe cron list --status pending

echo "==> soothe cron show $JOB_ID"
uv run soothe cron show "$JOB_ID"

echo "==> soothe cron add (cancel target)"
CANCEL_ADD_OUT="$(uv run soothe cron add "$CANCEL_TEXT" 2>&1)"
echo "$CANCEL_ADD_OUT"
CANCEL_ID="$(echo "$CANCEL_ADD_OUT" | grep -Eo 'ID:[[:space:]]+[a-f0-9]+' | awk '{print $2}' | head -1)"

echo "==> soothe cron cancel $CANCEL_ID"
uv run soothe cron cancel "$CANCEL_ID"

echo "==> soothe cron list --status cancelled"
CANCELLED_LIST="$(uv run soothe cron list --status cancelled)"
echo "$CANCELLED_LIST"
echo "$CANCELLED_LIST" | grep -q "${CANCEL_ID:0:6}"

echo "==> Cleanup pending e2e jobs"
uv run soothe cron cancel "$JOB_ID" || true
uv run soothe cron cancel "$HEADLESS_ID" || true

echo ""
echo "Cron E2E passed."
echo "  add job:      $JOB_ID"
echo "  headless job: $HEADLESS_ID"
echo "  cancelled:    $CANCEL_ID"
