# Soothe

Goal-driven multi-agent orchestration framework (in-process host core).

Extends [soothe-nano](https://github.com/mirasoth/soothe-nano) with StrangeLoop
planning, durability, and Autopilot (daemon-dispatched). For a lightweight
one-shot coding CLI on nano alone, see [fj-ai](https://github.com/caesar0301/fj-ai).

## Installation

Full runtime (daemon + CLI):

```bash
pip install soothe soothe-daemon soothe-cli
```

Library only (this package):

```bash
pip install soothe
```

## What's in this package

| Piece | Role |
|-------|------|
| `SootheRunner` | Protocol orchestration + StrangeLoop stream (`astream`) |
| `create_soothe_agent` | Host CoreAgent factory (planner/policy/memory wired) |
| `SootheConfig` | Nano base + host overlay (`nano.yml` / `soothe.yml`) |
| StrangeLoop / Autopilot / CE / cron | Host orchestration (Autopilot needs the daemon) |

## Quick example (StrangeLoop, non-autopilot)

In-process, fj-style one-shot — no daemon:

```python
import asyncio
from soothe.config import SootheConfig
from soothe.runner import SootheRunner

async def main() -> None:
    config = SootheConfig.from_yaml_file("~/.soothe/config/nano.yml")
    runner = SootheRunner(config)
    try:
        async for _ns, mode, data in runner.astream("Summarize this repo"):
            if mode == "messages":
                print(data)  # (message, metadata)
    finally:
        await runner.cleanup()

asyncio.run(main())
```

Runnable script (loads `~/.soothe/config`, SQLite defaults, prints progress):

```bash
uv run python examples/01_strange_loop_example.py
```

Pass `autopilot_job=...` only when embedding a daemon-dispatched worker goal.
Interactive / library use should omit it so StrangeLoop runs the user query.

## Related packages

| Package | Purpose |
|---------|---------|
| `soothe-daemon` | Long-running server (HTTP/WS, channels, Autopilot dispatch) |
| `soothe-cli` | Human CLI + Textual TUI |
| `soothe-sdk` | Shared wire contracts and types |
| `soothe-nano` | SootheNanoAgent (tools, skills, MCP) |

## Testing

```bash
uv run pytest packages/soothe/tests/unit/ -v
```
