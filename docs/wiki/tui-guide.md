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
| `/thread list` | List all conversation threads |
| `/thread resume <id>` | Resume a specific thread |
| `/thread archive <id>` | Archive a thread |
| `/config` | Show active configuration |
| `/clear` | Clear the screen |
| `/detach` | Detach TUI; daemon keeps running |
| `/exit` or `/quit` | Stop daemon and exit TUI |

### Subagent Routing Commands

Route queries to specialized subagents:

| Command | Subagent | Use Case |
|---------|----------|----------|
| `/browser <query>` | Browser Agent | Web browsing and automation |
| `/claude <query>` | Claude Agent | Complex reasoning with Claude |
| `/skillify <query>` | Skillify Agent | Skill retrieval and discovery |
| `/weaver <query>` | Weaver Agent | Agent generation |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Q` | Quit Soothe (stops daemon) |
| `Ctrl+D` | Detach TUI (daemon keeps running) |
| `Ctrl+C` | Cancel running job |
| `Ctrl+E` | Focus chat input |
| `Ctrl+Y` | Copy last message to clipboard |

## Routing to Specialized Subagents

Prefix your message with a number to route to a specific subagent:

| Prefix | Subagent | Best For |
|--------|----------|----------|
| `1` | Main | General tasks (default) |
| `5` | Browser | Web browsing and automation |
| `6` | Claude | Tasks requiring Claude's strengths |
| `7` | Skillify | Retrieving relevant skills |
| `8` | Weaver | Generating specialized agents |

**Examples:**

```
5 Open https://example.com and take a screenshot
6 Analyze this complex reasoning problem
7 Find relevant skills for data processing
```

## Multi-Line Input

Continue your input on multiple lines by ending with `\`:

```
soothe> Write a function that \
...  takes a list of numbers \
...  and returns the median
```

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
soothe server attach
```

## Viewing Progress

The TUI shows real-time progress through:
- **Plan Panel**: Task decomposition and step status
- **Activity Panel**: Last 5 lines of subagent activity and tool calls
- **Conversation Panel**: User turns and final responses

## Related Guides

- [CLI Reference](cli-reference.md) - Complete command-line documentation
- [Subagents Guide](subagents.md) - Learn about specialized subagents
- [Autonomous Mode](autonomous-mode.md) - Enable autonomous iteration