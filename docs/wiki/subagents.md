# Specialized Subagents

Core Soothe ships five built-in subagents: **explore**, **plan**, **tacitus**, **browser_use**, and **veritas**. Additional optional delegated agents (e.g. **skillify**, **weaver**, and other community plugins) are maintained in the **`soothe-plugins`** package—see that project's README and docs.

## Overview

| Subagent | Slash Command | Prefix | Best For |
|----------|--------------|--------|----------|
| Tacitus | `/tacitus <query>` | (see TUI guide) | Multi-source public-domain research |
| Explore | `/explore <query>` | (see TUI guide) | Readonly repository search |
| Plan | `/plan` or `/plan <prompt>` | — | Plan-mode routing |
| Browser Use | `/browser_use <url>` | (see TUI guide) | Browser automation and web interaction |
| Veritas | (auto-invoked) | — | Clarification auto-answerer in autonomous mode |

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

## Browser Use Agent

Browser automation specialist for web navigation and interaction.

**Capabilities**:
- Navigate pages and interact with elements (click, fill forms)
- Extract content from web pages
- Take screenshots for verification
- Handle JavaScript-heavy dynamic pages

**Usage**:
```bash
# In TUI
/browser_use Navigate to https://example.com and extract the main heading

# Form automation
/browser_use Fill out the contact form on https://example.com/contact
```

**Configuration**:
```yaml
subagents:
  browser_use:
    enabled: true
    # Optional: browser automation settings
    headless: true
    max_steps: 50
```

**Note**: Browser Use requires the `browser-use` library. If not installed, the subagent's `on_load` hook raises a `PluginError` with install instructions.

## Veritas Agent

Intent-grounded clarification auto-answerer for autonomous mode.

**Capabilities**:
- Automatically answers clarification questions when the StrangeLoop pauses on an `ask_user` interrupt
- Uses the goal's first-principles context to produce best-effort answers
- Defers to manual resolution when confidence is insufficient

**Usage**: Veritas is automatically invoked by the `AutoClarificationPolicy` when the loop pauses. No manual slash command is needed.

**Configuration**:
```yaml
subagents:
  veritas:
    enabled: true
```

**Note**: Veritas is a single structured-output LLM call (not a CoreAgent). When it cannot answer with sufficient confidence, it sets `defer=True` and the loop transitions the goal to `awaiting_clarification` for out-of-band resolution.

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
/plan <prompt>     # Route to Plan
/browser_use <url> # Route to Browser Use
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

### Browser Automation
```bash
/browser_use Navigate to https://news.ycombinator.com and list the top 5 stories
```

## Optional Plugin Subagents

The `soothe-plugins` package provides additional delegate subagents that are not part of core:

- **Skillify**: Skill retrieval and discovery (`/skillify`)
- **Weaver**: Agent generation (`/weaver`)
- **Claude**: Claude Code integration

Install `soothe-plugins` and follow its README for provider keys, extras, and `subagents.*` YAML configuration.

## Related Guides

- [TUI Guide](tui-guide.md) - Slash commands and routing
- [Configuration Guide](configuration.md) - Subagent configuration
- [Troubleshooting](troubleshooting.md) - Common subagent issues
