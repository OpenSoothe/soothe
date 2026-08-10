#!/usr/bin/env bash
# Rewrite mirror registry/wheel URLs in uv.lock back to canonical PyPI hosts.
#
# `uv sync --default-index <mirror>` rewrites package `source.registry` and
# wheel/sdist URLs to the mirror. CI and other environments expect the
# committed lock to reference https://pypi.org/simple + files.pythonhosted.org.
# Prefer this over `git checkout -- uv.lock` so dependency bumps from sync/lock
# are kept while URLs stay PyPI-canonical.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="${1:-$ROOT/uv.lock}"

if [[ ! -f "$LOCK" ]]; then
  echo "rewrite_uv_lock_to_pypi: missing $LOCK" >&2
  exit 1
fi

python3 - "$LOCK" <<'PY'
from pathlib import Path
import re
import sys

MIRROR_HOSTS = ("mirrors.cloud.tencent.com", "pypi.tuna.tsinghua.edu.cn", "mirrors.aliyun.com")
HOST_ALT = "|".join(re.escape(host) for host in MIRROR_HOSTS)

lock = Path(sys.argv[1])
text = lock.read_text()
# Mirrors serve the file store under varying prefixes (e.g. /pypi/packages/,
# /yun/pypi/packages/), so match any prefix ahead of the packages/ segment.
text = re.sub(
    rf"https://(?:{HOST_ALT})/(?:[\w.-]+/)*packages/",
    "https://files.pythonhosted.org/packages/",
    text,
)
text = re.sub(
    rf'registry = "https://(?:{HOST_ALT})/(?:[\w.-]+/)*simple/?"',
    'registry = "https://pypi.org/simple"',
    text,
)
lock.write_text(text)
bad = sorted({host for host in MIRROR_HOSTS if host in text})
if bad:
    raise SystemExit(f"rewrite_uv_lock_to_pypi: leftover mirror hosts: {bad}")
PY
