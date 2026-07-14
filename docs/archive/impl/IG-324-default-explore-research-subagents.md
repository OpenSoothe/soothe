# IG-324: Default explore + research subagents; remove tools.research

## Goal

- Ship **`explore`** and **`research`** in the same default merged `subagents` map as **`browser`** and **`claude`** (`SootheConfig._merge_subagents`).
- Remove obsolete **`tools.research`** (`ToolsConfig`) and template YAML; research is **subagent-only** (RFC-0021).

## Status

Implemented.
