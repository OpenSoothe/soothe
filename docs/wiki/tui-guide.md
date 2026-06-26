# TUI Guide

Master the Soothe terminal user interface (TUI).

## Interface Overview

The Soothe TUI provides a rich, interactive terminal interface with:
- **Chat Input**: Type your messages and commands
- **Conversation Panel**: View the conversation history
- **Plan Panel**: Track task decomposition and progress
- **Activity Panel**: Monitor subagent activity and tool usage

## Slash Commands

Type these commands in the interactive prompt:

| Command | Description |
|---------|-------------|
| `/help` | Show all commands and available subagents |
| `/keymaps` | Show keyboard shortcuts |
| `/autopilot <prompt>` | Run one prompt in autonomous mode |
| `/autopilot <max_iterations> <prompt>` | Run in autonomous mode with custom iteration limit |
| `/cancel` | Cancel the current running job |
| `/plan` | Show the current task plan |
| `/memory` | Show memory statistics |
| `/context` | Show context statistics |
| `/policy` | Show active policy profile |
| `/history` | Show recent prompt history |
| `/review [conversation\|actions]` | Review recent conversation and actions |
| `/resume` | Resume a recent thread (interactive selection) |
| `/thread archive <id>` | Archive a thread |
| `/config` | Show active configuration |
| `/clear` | Clear the screen |
| `/detach` | Detach TUI; daemon keeps running |
| `/exit` or `/quit` | Stop daemon and exit TUI |

### Subagent Routing Commands

Route queries to specialized subagents:

| Command | Subagent | Use Case |
|---------|----------|----------|
| `/tacitus <query>` | Tacitus | Multi-source public-domain research |
| `/explore <query>` | Explore | Readonly repo search |
| `/plan` | Plan | Plan-mode routing |
| `/«id» <query>` | Configured id | Optional plugins from soothe-plugins (see that repo for ids) |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Q` | Quit Soothe (stops daemon) |
| `Ctrl+D` | Detach TUI (daemon keeps running) |
| `Ctrl+C` | Cancel running job |
| `Ctrl+E` | Focus chat input |
| `Ctrl+Y` | Copy last message to clipboard |
| `Ctrl+T` | Toggle plan panel visibility |
| `Shift+Enter` | Insert newline in chat input |
| `Enter` | Submit message |
| `Up/Down` | Navigate input history |

## Routing to Specialized Subagents

Prefix your message with a number to route to a specific subagent:

| Prefix | Subagent | Best For |
|--------|----------|----------|
| `1` | Main | General tasks (default) |
| `7` | Skillify | Retrieving relevant skills |
| `8` | Weaver | Generating specialized agents |

Numeric slots `2`–`6` are reserved for optional installs; see soothe-plugins for the current mapping on your distribution.

**Examples:**

```
7 Find relevant skills for data processing
8 Generate a specialized agent for monitoring uptime
```

## Multi-Line Input

Type multi-line messages using **Shift+Enter** to insert a newline:

```
soothe> Write a function that
...  takes a list of numbers
...  and returns the median
```

Press **Enter** to submit the message when ready.

## Canceling Operations

- `Ctrl+C` once: Cancel current task
- `Ctrl+C` twice: Exit the TUI

## Detached Mode

Detach the TUI while keeping the daemon running:

```bash
# In TUI
/detach

# Or use keyboard shortcut
Ctrl+D
```

Reattach later:

```bash
# Resume via running daemon
soothe thread continue --daemon
```

## Viewing Progress

The TUI shows real-time progress through:
- **Plan Panel**: Task decomposition and step status
- **Activity Panel**: Last 5 lines of subagent activity and tool calls
- **Conversation Panel**: User turns and final responses
- **Step Cards**: Tool activity preview and file change previews

## Step Cards

Step cards (`CognitionStepMessage`) show progress for each plan step during StrangeLoop execution. **Normative spec: [RFC-628](../specs/RFC-628-step-card-display-refactor.md).**

### Layout

Each step card has five zones (header always visible; others hide when manually collapsed):

| Zone | Content |
|------|---------|
| **Header** | Step description only (`🚀 …`) |
| **Activity tree** | Task branches, tool previews, branch status lines |
| **Detail** | Streaming execute prose, clarification Q&A, or errors |
| **Footer** | Pending / Queued / Running / Completed status |
| **Tools panel** | Optional full nested list (off by default) |

Click the card to manually collapse or expand the body. Cards do **not** auto-collapse.

### Tool activity preview

- **Cap**: Latest **3** tool invocation lines **per scope** (main-agent, each task branch, orphan subgraph)
- **Format**: Goal-tree gutter (`⎿`), phase icon, `ToolName(args)`, optional status tail
- **Task branches**: `Explore(description)` header with nested child tools indented underneath

**Example** (running step with one task delegation and main tools):

```
🚀 Survey RFCs and update wiki
⎿ ✓ Explore(enumerate docs)
⎿   ○ ReadFile(docs/specs/RFC-628…)
⎿   ○ Glob(**/*.md)
⎿   ⠋ Running... (8s) · 2 tools
⎿ ○ Grep(pattern="step card")
⎿ ⠋ Running... (45s) · 3 tools
⎿ ⠋ Running... (45s) · 3 tools, 1 task
```

The last line is the **footer**; lines above are the **activity tree**. Running lines include `· N tools` for their scope; the footer shows **total** tools (main + subgraph) plus task count.

### Stats on running lines

| Line | Tool count scope |
|------|------------------|
| Task branch Running | Child tools under that delegation |
| Main branch Running | Direct main-agent tools |
| Orphan branch Running | Subgraph tools without visible task parent |
| Footer Running | **Total** tools on step + `, M tasks` when delegations exist |

Token usage (`in:… out:…`) and retry counts append on the footer when available.

### File change preview

When files are modified, the TUI displays a diff preview widget:

- **Trigger**: Appears automatically on file edit operations
- **Content**: Shows unified diff of changes (added/removed lines)
- **Navigation**: Scroll through changes with arrow keys
- **Dismiss**: Press `q` or `Esc` to close the preview

**Features**:
- Syntax highlighting for common file types
- Line numbers for reference
- Collapsed context around changes
- Summary statistics (files changed, insertions, deletions)

## Streaming Performance

The TUI has been optimized for low-latency streaming:

- **Reduced Event Volume**: Server-side batching reduces WebSocket events by ~80%
- **Priority Queue**: Tool updates display before text streaming completes
- **Fast Drain**: Post-goal completion drain time reduced from ~50s to <5s
- **Coalesced Text**: Plain assistant text is buffered and delivered in chunks

These optimizations ensure the UI stays responsive even during long-running tasks with heavy output.

## Related Guides

- [CLI Reference](cli-reference.md) - Complete command-line documentation
- [Subagents Guide](subagents.md) - Learn about specialized subagents
- [Autonomous Mode](autonomous-mode.md) - Enable autonomous iteration