"""Temporary diagnostic: spawn pool worker; run manually then delete if unused."""
from __future__ import annotations

import multiprocessing as mp
import time
from pathlib import Path

from soothe.config.settings import SootheConfig
from soothe_daemon.runner.pool_runner import _pool_worker, _spawn_safe_config


def main() -> None:
    cfg_path = Path.home() / ".soothe" / "config" / "config.yml"
    if not cfg_path.exists():
        cfg_path = Path(__file__).resolve().parents[4] / "config" / "config.dev.yml"
    cfg = SootheConfig.from_yaml_file(str(cfg_path))
    safe = _spawn_safe_config(cfg)

    ctx = mp.get_context("spawn")
    rq = ctx.Queue()
    sq = ctx.Queue()
    ce = ctx.Event()
    iq = ctx.Queue()

    p = ctx.Process(
        target=_pool_worker,
        args=(
            safe,
            "diag-worker-0",
            rq,
            sq,
            ce,
            iq,
            300,
            100,
            1800,
            30,
        ),
        daemon=True,
        name="diag-worker-0",
    )
    p.start()
    time.sleep(0.2)
    print("pid", p.pid, "alive", p.is_alive(), "exitcode", p.exitcode)
    rq.put(None)
    p.join(timeout=20)
    print("after join alive", p.is_alive(), "exitcode", p.exitcode)


if __name__ == "__main__":
    main()
