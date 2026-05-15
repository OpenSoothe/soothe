# Specialized Subagents

Core Soothe ships **explore**, **plan**, and **research** subagents. Additional optional delegated agents (extra slash commands, numeric prefixes, and install steps) are maintained in the **`soothe-community`** repository—see that project’s README and docs.

## Overview

| Subagent | Slash Command | Prefix | Best For |
|----------|--------------|--------|----------|
| Research | `/research <query>` | (see TUI guide) | Multi-source investigation |
| Explore | `/explore <query>` | (see TUI guide) | Readonly repository search |
| Plan | `/plan` or `/plan <prompt>` | — | Plan-mode routing |
| Skillify | `/skillify <query>` | `7` | Skill retrieval and discovery |
| Weaver | `/weaver <query>` | `8` | Agent generation |

## Skillify Agent

Skill warehouse and retrieval system.

**Capabilities**:
- Retrieve relevant skills
- Discover patterns and best practices
- Apply learned workflows
- Index and search skill embeddings

**Installation**:
```bash
pip install soothe[pgvector]  # For vector storage
```

**Usage**:
```bash
# In TUI
/skillify Find skills for data processing workflows

# With prefix
7 Retrieve relevant skills for building a REST API
```

**Configuration**:
```yaml
subagents:
  skillify:
    enabled: true
    warehouse_paths: []  # Additional warehouse paths
    index_interval_seconds: 300  # Background indexing interval
    index_collection: "soothe_skillify"  # Vector collection name
    retrieval_top_k: 10  # Number of results to retrieve
```

## Weaver Agent

Agent generation system for creating specialized agents.

**Capabilities**:
- Generate specialized agents
- Analyze requirements
- Compose agent code
- Reuse existing patterns

**Usage**:
```bash
# In TUI
/weaver Create an agent for analyzing PDF documents

# With prefix
8 Generate a specialized agent for monitoring website uptime
```

**Configuration**:
```yaml
subagents:
  weaver:
    enabled: true
    reuse_index_collection: "soothe_weaver_reuse"  # Vector collection for reuse
```

## Subagent Routing

### Slash Commands

Direct routing with slash commands for core agents:
```bash
/research <query>  # Route to Research
/explore <query>   # Route to Explore
/skillify <query>  # Route to Skillify
/weaver <query>    # Route to Weaver
```

### Prefix Routing

Route with numeric prefix (see [TUI Guide](tui-guide.md) for the current mapping on your install).

### Default Behavior

Without a prefix or slash command, queries go to the Main agent (prefix `1`):
```bash
<query>  # Route to Main agent
```

## Examples

### Research
```bash
/research Compare vector databases for RAG workloads
```

### Explore
```bash
/explore Find where authentication middleware is registered
```

### Skill Discovery
```bash
/skillify Find patterns for implementing retry logic with exponential backoff
```

### Agent Generation
```bash
/weaver Create an agent that monitors SSL certificate expiration dates
```

## Related Guides

- [TUI Guide](tui-guide.md) - Slash commands and routing
- [Configuration Guide](configuration.md) - Subagent configuration
- [Troubleshooting](troubleshooting.md) - Common subagent issues
