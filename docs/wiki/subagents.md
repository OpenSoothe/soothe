# Specialized Subagents

Core Soothe ships **explore**, **plan**, and **tacitus** subagents. Additional optional delegated agents (extra slash commands, numeric prefixes, and install steps) are maintained in the **`soothe-community`** repository—see that project’s README and docs.

## Overview

| Subagent | Slash Command | Prefix | Best For |
|----------|--------------|--------|----------|
| Tacitus | `/tacitus <query>` | (see TUI guide) | Multi-source public-domain research |
| Explore | `/explore <query>` | (see TUI guide) | Readonly repository search |
| Plan | `/plan` or `/plan <prompt>` | — | Plan-mode routing |
| Skillify | `/skillify <query>` | `7` | Skill retrieval and discovery |
| Weaver | `/weaver <query>` | `8` | Agent generation |

## Tacitus Agent

Public-domain research assistant for multi-source investigation using only public sources.

**Capabilities**:
- Web search via multiple engines
- Wikipedia article retrieval
- Academic paper search (arXiv, PubMed Central)
- URL content crawling and extraction
- Semantic capability routing for source selection

**Data Sources**:
| Source | Capability | Description |
|--------|------------|-------------|
| Web Search | `web_search` | Multi-engine web search (Tavily, DuckDuckGo, Brave) |
| Wikipedia | `wikipedia` | Wikipedia article content and summaries |
| Academic | `academic_search` | arXiv, bioRxiv, medRxiv, PubMed Central |
| URL Crawl | `url_crawl` | Direct webpage content extraction |

**Usage**:
```bash
# In TUI
/tacitus Compare vector databases for RAG workloads

# Research with specific focus
/tacitus What are the latest advances in quantum error correction?
```

**Effort levels** (default: `normal`):

| Level | Sub-questions | Queries | Reflection loops | Use when |
|-------|---------------|---------|------------------|----------|
| `normal` | up to 3 | up to 4 | 2 | Fast lookup, lighter research |
| `high` | up to 5 | up to 6 | 3 | Balanced depth |
| `xhigh` | up to 8 | up to 10 | 5 | Maximum breadth and follow-ups |

Set in config (`effort: high`) or in the task description (`effort: xhigh` on the first line). The final report includes a formatted **References** section with URLs collected during gather.

**Configuration**:
```yaml
subagents:
  tacitus:
    enabled: true
    config:
      effort: normal  # normal | high | xhigh
    # Optional: configure source preferences
    sources:
      web_search:
        enabled: true
      wikipedia:
        enabled: true
      academic:
        enabled: true
      url_crawl:
        enabled: true
```

**Note**: Tacitus uses semantic capability routing to automatically select the most appropriate sources for your query. It only accesses public-domain sources and does not perform filesystem operations or CLI commands.

## Explore Agent

Readonly filesystem and repository exploration agent.

**Capabilities**:
- Search and explore codebases without making changes
- Find files, functions, and patterns
- Read file contents and directory structures
- Analyze git history and repository metadata
- Gather context for planning and implementation

**Usage**:
```bash
# In TUI
/explore Find where authentication middleware is registered

# Explore specific patterns
/explore Show me all places where the config is loaded
```

**Configuration**:
```yaml
subagents:
  explore:
    enabled: true
    # Optional: configure search behavior
    max_iterations: 10  # Maximum exploration iterations
    max_files_per_iteration: 20  # Files to examine per iteration
```

**Note**: Explore is designed for readonly operations only. It cannot modify files or execute commands. Use it to understand codebases before making changes.

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

## Plan Agent

Planning and task decomposition agent for complex multi-step tasks.

**Capabilities**:
- Decompose complex goals into actionable steps
- Assess task progress and completion
- Generate evidence-based plans
- Handle replanning when circumstances change
- Coordinate with other subagents for execution

**Usage**:
```bash
# In TUI - show current plan
/plan

# In TUI - plan a specific task
/plan Create a REST API with authentication and rate limiting
```

**Configuration**:
```yaml
subagents:
  plan:
    enabled: true
    # Optional: configure planning behavior
    max_steps: 20  # Maximum steps in a plan
    evidence_bundle: true  # Enable progressive evidence gathering
```

**Note**: The Plan agent is automatically invoked during autonomous mode. You can also use `/plan` manually to review or create plans.

## Subagent Routing

### Slash Commands

Direct routing with slash commands for core agents:
```bash
/tacitus <query>    # Route to Tacitus
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

### Tacitus
```bash
/tacitus Compare vector databases for RAG workloads
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
