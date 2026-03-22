# Specialized Subagents

Soothe provides four specialized subagents for different tasks.

## Overview

| Subagent | Slash Command | Prefix | Best For |
|----------|--------------|--------|----------|
| Browser | `/browser <query>` | `5` | Web browsing and automation |
| Claude | `/claude <query>` | `6` | Complex reasoning with Claude |
| Skillify | `/skillify <query>` | `7` | Skill retrieval and discovery |
| Weaver | `/weaver <query>` | `8` | Agent generation |

## Browser Agent

Automated web browsing and automation.

**Capabilities**:
- Navigate pages
- Fill forms
- Click elements
- Take screenshots
- Extract content

**Installation**:
```bash
pip install soothe[browser]
```

**Usage**:
```bash
# In TUI
/browser Open https://example.com and extract the main content

# With prefix
5 Navigate to the login page and fill the form with test credentials
```

**Privacy**: Extensions, cloud sync, and telemetry are disabled by default.

**Configuration**:
```yaml
subagents:
  browser:
    enabled: true
    config:
      runtime_dir: ""  # Empty = use SOOTHE_HOME/agents/browser/
      disable_extensions: true  # Disable uBlock Origin, cookie handler
      disable_cloud: true  # Disable browser-use cloud service
      disable_telemetry: true  # Disable anonymous telemetry
```

## Claude Agent

Direct access to Claude for complex reasoning tasks.

**Capabilities**:
- Long context reasoning (200K tokens)
- Careful analysis
- Complex problem-solving
- Nuanced understanding

**Installation**:
```bash
pip install soothe[claude]
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**Usage**:
```bash
# In TUI
/claude Analyze this complex argument and identify logical fallacies

# With prefix
6 Provide a detailed analysis of this research paper's methodology
```

**Configuration**:
```yaml
subagents:
  claude:
    enabled: true
    model: "anthropic:claude-sonnet-4-20250514"  # Optional override
```

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

Direct routing with slash commands:
```bash
/browser <query>   # Route to Browser
/claude <query>    # Route to Claude
/skillify <query>  # Route to Skillify
/weaver <query>    # Route to Weaver
```

### Prefix Routing

Route with numeric prefix:
```bash
5 <query>  # Route to Browser
6 <query>  # Route to Claude
7 <query>  # Route to Skillify
8 <query>  # Route to Weaver
```

### Default Behavior

Without a prefix or slash command, queries go to the Main agent (prefix `1`):
```bash
<query>  # Route to Main agent
```

## Examples

### Web Browsing
```bash
/browser Open https://news.ycombinator.com and extract the top 5 stories
```

### Complex Analysis
```bash
/claude Analyze this codebase and identify potential security vulnerabilities
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