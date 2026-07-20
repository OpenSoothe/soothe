# soothe-nano

Batteries-included **Coding CoreAgent** for Soothe — built on `soothe-deepagents`
(tools, subagents, skills, MCP), without StrangeLoop, Autopilot, or daemon.

Full `soothe` depends on this package. See [IG-668](../../docs/impl/IG-668-soothe-nano-package-extract.md).

## Install

```bash
uv add soothe-nano
```

## Quick start (Phase A+)

```python
from soothe_nano import CodingCoreAgent, LazyCoreAgent

# Factory (`create_nano_agent`) lands in Phase B; today full soothe still
# builds agents via `soothe.foundation.coreagent.create_soothe_agent`.
```

## Layout

```
soothe_nano/
  agent/       # CodingCoreAgent, LazyCoreAgent, execute helpers
  config/      # NanoConfig (Phase B)
  toolkits/    # Phase C
  subagents/   # Phase C
  middleware/  # Phase B/C
  skills/      # Phase C
  mcp/         # Phase C
  ...
```
