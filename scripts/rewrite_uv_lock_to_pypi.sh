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
import sys

lock = Path(sys.argv[1])
text = lock.read_text()
repls = (
    (
        "https://mirrors.cloud.tencent.com/pypi/packages/",
        "https://files.pythonhosted.org/packages/",
    ),
    (
        "https://pypi.tuna.tsinghua.edu.cn/packages/",
        "https://files.pythonhosted.org/packages/",
    ),
    (
        "https://mirrors.aliyun.com/pypi/packages/",
        "https://files.pythonhosted.org/packages/",
    ),
    (
        'registry = "https://mirrors.cloud.tencent.com/pypi/simple"',
        'registry = "https://pypi.org/simple"',
    ),
    (
        'registry = "https://pypi.tuna.tsinghua.edu.cn/simple"',
        'registry = "https://pypi.org/simple"',
    ),
    (
        'registry = "https://mirrors.aliyun.com/pypi/simple"',
        'registry = "https://pypi.org/simple"',
    ),
)
for old, new in repls:
    text = text.replace(old, new)
lock.write_text(text)
bad = [s for s in ("tuna.tsinghua", "mirrors.cloud.tencent", "mirrors.aliyun") if s in text]
if bad:
    raise SystemExit(f"rewrite_uv_lock_to_pypi: leftover mirror hosts: {bad}")
PY
