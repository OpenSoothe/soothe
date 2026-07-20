# soothe-nano

Batteries-included **Coding CoreAgent** for Soothe — built on `soothe-deepagents`
(tools, subagents, skills, MCP), without StrangeLoop, Autopilot, or daemon.

## Who depends on this package

| Package | Relationship |
|---------|----------------|
| `soothe` | Host composition (StrangeLoop / Autopilot / runner) |
| `soothe-daemon` | Direct runtime imports (skills, MCP, backends, identity middleware) |
| `soothe-plugins` | Community plugins (no full `soothe` dependency) |

See [IG-668](../../docs/impl/IG-668-soothe-nano-package-extract.md).

## Install

```bash
uv add soothe-nano
```

## Quick start

```python
from soothe_nano import CodingCoreAgent, LazyCoreAgent, create_nano_agent
from soothe_nano.config import SootheConfig

config = SootheConfig()
agent = create_nano_agent(config)
```

Full `soothe` builds loop-aware agents via `soothe.foundation.coreagent.create_soothe_agent`
(which wraps nano and injects StrangeLoop planner hooks).

## Layout

```
soothe_nano/
  agent/       # CodingCoreAgent, LazyCoreAgent, create_nano_agent
  config/      # CoreAgent config slice
  toolkits/    # Builtin tool groups
  subagents/   # Core subagents (explore, research, plan, …)
  middleware/  # Progressive skills/tools, identity, …
  skills/      # Catalog + progressive search (substring)
  mcp/         # MCP registry/adapters
  backends/    # Persistence / vector helpers used by CoreAgent
  …
```
