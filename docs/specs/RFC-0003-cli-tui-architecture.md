nnn# RFC-0003: CLI TUI Architecture Design

**RFC**: 0003
**Title**: CLI TUI Architecture Design
**Status**: Implemented
**Created**: 2026-03-12
**Updated**: 2026-03-28
**Related**: RFC-0001, RFC-0002, RFC-0006

## Abstract

This RFC defines the architecture for the Soothe CLI's interactive terminal user interface (TUI). The CLI provides three interaction modes: Textual TUI (default), headless CLI, and daemon-based background execution with attach/detach. The TUI builds on the deepagents-canonical `astream()` pattern and extends it with protocol orchestration events.

## Overview

Soothe's CLI supports three interaction modes:

1. **Textual TUI (default)** — Full-featured interactive TUI that connects to a daemon. Provides real-time streaming progress, protocol observability, thread management, and dynamic subagent routing. Auto-starts the daemon if not running.

2. **Headless CLI** — Single-prompt execution with streaming output to stdout/stderr. Supports `--format jsonl` for machine-readable event output. No TUI required.

3. **Daemon-based background execution** — The daemon runs `SootheRunner` in the background and serves events over a Unix domain socket. Clients (TUI or headless) can attach, detach, and reconnect without losing the agent session.

## Motivation

RFC-0001 defines Soothe as an orchestration framework with seven core protocols. RFC-0002 specifies their interfaces and data models. However, neither RFC addresses how a human operator interacts with the running orchestrator. A 24/7 autonomous agent needs:

- Real-time progress visibility into planning, tool calls, subagent delegation, and protocol activity
- Thread lifecycle management (create, resume, suspend, list)
- Dynamic routing to subagents based on user intent or planner decisions
- Cross-thread memory relay for knowledge continuity
- Thread logging for offline audit and replay
- Ability to attach and detach from the agent without losing state

## Design Principles

### Native stream extension, not replacement

The TUI consumes the deepagents-canonical stream format: `(namespace, mode, data)` 3-tuples from `agent.astream(stream_mode=["messages", "updates", "custom"], subgraphs=True)`. Protocol events extend this as `custom` mode chunks with `soothe.*` type prefix. No separate event model is introduced.

### Protocol observability without coupling

Protocols are invoked before and after the LangGraph stream. Their activity is surfaced as lightweight custom events (plain dicts), not as modifications to the agent graph. The TUI renders them as one-liner activity indicators. Protocols remain independent of the presentation layer.

### Orchestration-layer runner

A `SootheRunner` class sits between the TUI and the raw agent graph. It handles protocol orchestration (context projection, memory recall, plan creation, policy checks) and thread lifecycle, yielding a unified stream. The TUI is a pure renderer — it does not call protocols directly.

## Architecture

```
+------------------------------------------------------------------+
|  CLI (ux/cli/main.py, Typer)                                      |
|  - Entry point, config loading, command routing                   |
|  - soothe | daemon | thread | config | agent | autopilot         |
+------------------------------------------------------------------+
|  Execution Surfaces                                               |
|  - Textual TUI (ux/tui/app.py): SootheApp via run_textual_tui()  |
|  - Headless CLI (ux/cli/execution/*): text or --format jsonl      |
|  - Daemon-backed attach/detach/resume flows                       |
+------------------------------------------------------------------+
|  Daemon (daemon/server.py + transports/*)                         |
|  - SootheDaemon lifecycle and event routing                       |
|  - DaemonClient for TUI/headless connections                      |
|  - Unix socket default; optional WebSocket and HTTP REST          |
+------------------------------------------------------------------+
|  SootheRunner (core/runner/*)                                     |
|  - Protocol orchestration (pre-stream / post-stream)              |
|  - LangGraph astream() pass-through                               |
|  - HITL interrupt loop                                            |
|  - Thread lifecycle coordination with ThreadContextManager        |
+------------------------------------------------------------------+
|  create_soothe_agent() -> CompiledStateGraph                      |
|  - deepagents middleware stack                                    |
|  - Subagents, tools, skills, protocol instances                   |
+------------------------------------------------------------------+
|  Protocols (context, memory, planner, policy, durability)         |
+------------------------------------------------------------------+
```

## Stream Architecture

### Stream format

The universal stream format is LangGraph's `(namespace, mode, data)` 3-tuple:

| Mode | Namespace | Data | Content |
|------|-----------|------|---------|
| `messages` | `()` (main) | `(AIMessage, metadata)` | LLM text tokens and tool call chunks |
| `messages` | non-empty | `(AIMessage, metadata)` | Subagent text and tool call chunks |
| `messages` | `()` (main) | `(ToolMessage, metadata)` | Tool execution results |
| `updates` | `()` (main) | `{"__interrupt__": [...]}` | HITL interrupts |
| `custom` | `()` or non-empty | `dict` | Subagent progress (e.g. `soothe.research.web_search`, `soothe.browser.step`) |
| `custom` | `()` (main) | `{"type": "soothe.*", ...}` | Protocol orchestration events |

All custom events follow the `soothe.<component>.<action>` naming convention. Subagent events use `soothe.<subagent>.<action>` (e.g. `soothe.research.*`, `soothe.browser.*`, `soothe.claude.*`, `soothe.skillify.*`, `soothe.weaver.*`). Protocol events use `soothe.<protocol>.<action>` (e.g. `soothe.plan.*`, `soothe.policy.*`). The `classify_custom_event()` function distinguishes subagent events from protocol events using an explicit `_SUBAGENT_PREFIXES` set.

### Protocol custom events

Protocol events follow the naming convention `soothe.<protocol>.<action>`:

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.thread.started` | `thread_id`, `protocols` | Thread began |
| `soothe.thread.ended` | `thread_id` | Thread complete |
| `soothe.context.projected` | `entries`, `tokens` | Context projection for query |
| `soothe.context.ingested` | `source`, `content_preview` | Knowledge ingested into context |
| `soothe.memory.recalled` | `count`, `query` | Cross-thread memories retrieved |
| `soothe.memory.stored` | `id`, `source_thread` | Memory auto-stored after response |
| `soothe.plan.created` | `goal`, `steps` | Plan created by PlannerProtocol |
| `soothe.plan.step_started` | `step_id`, `description`, `depends_on`, `batch_index` | Plan step execution began |
| `soothe.plan.step_completed` | `step_id`, `success`, `result_preview`, `duration_ms` | Plan step finished |
| `soothe.plan.step_failed` | `step_id`, `error`, `blocked_steps` | Plan step failed |
| `soothe.plan.batch_started` | `batch_index`, `step_ids`, `parallel_count` | Parallel step batch launched |
| `soothe.goal.batch_started` | `goal_ids`, `parallel_count` | Parallel goal batch launched |
| `soothe.goal.report` | `goal_id`, `step_count`, `completed`, `failed`, `summary` | Goal report (autonomous) |
| `soothe.plan.reflected` | `should_revise`, `assessment` | Planner reflection on results |
| `soothe.policy.checked` | `action`, `verdict`, `profile` | Policy check performed |
| `soothe.policy.denied` | `action`, `reason`, `profile` | Action denied by policy |
| `soothe.thread.created` | `thread_id` | New thread created |
| `soothe.thread.resumed` | `thread_id` | Existing thread resumed |
| `soothe.thread.saved` | `thread_id` | Thread state persisted |

### Event Rendering

For detailed event rendering behavior (two-level tree structure for tool calls, special tool behaviors, plan visualization, and text formatting), see **IG-053: CLI/TUI Event Progress Clarity**. The rendering layer is implementation-level and documented in implementation guides rather than this architectural RFC.

### Three-phase execution model

Each user query is processed in three phases:

**Phase 1: Protocol pre-processing** (yields `soothe.*` custom events)
1. Thread management via `DurabilityProtocol`
2. Context restoration via `ContextProtocol.restore()` (when resuming)
3. Policy check on user request via `PolicyProtocol`
4. Context projection via `ContextProtocol.project()`
5. Memory recall via `MemoryProtocol.recall()`
6. Plan creation via `PlannerProtocol.create_plan()` (if enabled)
7. Enriched input assembly (context + memories prepended to user message)

**Phase 2: LangGraph stream** (yields native stream chunks)
- `agent.astream()` with `stream_mode=["messages", "updates", "custom"]` and `subgraphs=True`
- HITL interrupt loop: collect `__interrupt__` from updates, auto-approve, resume with `Command(resume=...)`
- All chunks passed through to the TUI as-is

**Note**: RFC-0009 extends Phase 2 with a StepScheduler-driven step loop for multi-step plans. Each plan step becomes a separate LangGraph invocation, with independent steps executing in parallel based on DAG dependencies.

**Phase 3: Protocol post-processing** (yields `soothe.*` custom events)
1. Context ingestion of agent response via `ContextProtocol.ingest()`
2. Context persistence via `ContextProtocol.persist()`
3. Memory storage for significant findings via `MemoryProtocol.remember()`
4. Plan reflection via `PlannerProtocol.reflect()` (if plan active)
5. Thread-lifecycle persistence continues through `ThreadContextManager` during suspend/archive transitions rather than through a `DurabilityProtocol.save_state()` API

## IPC Protocol

The daemon communicates with clients over multiple transport protocols as defined in **RFC-0013: Unified Daemon Communication Protocol for Multi-Transport IPC**.

### Supported Transports

1. **Unix Domain Socket** (default local transport, fully implemented)
   - Path: `$SOOTHE_HOME/soothe.sock`
   - Protocol: Newline-delimited JSON
   - Use case: Local CLI and TUI clients
   - Authentication: None (filesystem permissions)

2. **WebSocket** (implemented transport module, see RFC-0013)
   - Default port: `8765` (localhost by configuration)
   - Protocol: WebSocket text frames
   - Use case: Web and Desktop applications (real-time streaming)
   - Authentication: Configurable; remote exposure depends on deployment hardening

3. **HTTP REST API** (implemented transport module, see RFC-0013)
   - Default port: `8766` (localhost by configuration)
   - Protocol: HTTP/1.1 with JSON bodies
   - Use case: Web and Desktop applications (status, thread operations, management endpoints)
   - Authentication: Configurable; some routes remain thin wrappers/placeholders in current code

### Unix Socket IPC (Current Default Path)

The Unix socket transport uses newline-delimited JSON and is the default local client path used by the Textual TUI and daemon-backed headless CLI.

#### Server → Client Messages

| Type | Fields | Description |
|------|--------|-------------|
| `event` | `namespace`, `mode`, `data` | Stream chunk from SootheRunner (canonical `(namespace, mode, data)` format) |
| `status` | `thread_id`, `state`, `input_history` | Daemon state: `idle`, `running`, `stopped`, `stopping`, `detached` |
| `command_response` | `content` | Output from slash command execution |
| `clear` | — | Clear screen command |

#### Client → Server Messages

| Type | Fields | Description |
|------|--------|-------------|
| `input` | `text`, `autonomous`, `max_iterations`, `subagent` | User message to send to the agent |
| `command` | `cmd` | Slash command (e.g. `/help`, `/plan`) |
| `detach` | — | Client detaching; daemon keeps running |
| `resume_thread` | `thread_id` | Resume a specific thread |
| `new_thread` | — | Start a new thread |

**Note**: For WebSocket and HTTP REST API message formats, see **RFC-0013**.

## CLI Commands

All commands follow the pattern: `soothe <subcommand> <action> [options]`

| Command | Description |
|---------|-------------|
| `soothe` | Interactive TUI mode (default). |
| `soothe -p "prompt" --no-tui` | Headless single prompt; stream to stdout/stderr via daemon-backed execution. |
| `soothe -p "prompt" --no-tui --format jsonl` | Headless with JSONL event output. |
| `soothe autopilot run "task"` | Autonomous execution mode. |
| `soothe daemon start` | Start daemon in background. |
| `soothe daemon start --foreground` | Start daemon in foreground. |
| `soothe daemon stop` | Stop the running daemon. |
| `soothe daemon status` | Show daemon status. |
| `soothe daemon restart` | Restart the daemon. |
| `soothe config show` | Show current configuration. |
| `soothe config init` | Initialize `$SOOTHE_HOME` (config, threads, logs). |
| `soothe config validate` | Validate configuration file. |
| `soothe thread list` | List all threads. |
| `soothe thread show <id>` | Show thread details. |
| `soothe thread continue [id]` | Continue a thread (launches TUI). Omit ID to continue last active. |
| `soothe thread archive <id>` | Archive a thread. |
| `soothe thread delete <id>` | Permanently delete a thread. |
| `soothe thread export <id>` | Export thread to jsonl or md. |
| `soothe thread stats <id>` | Show thread statistics. |
| `soothe thread tag <id> <tags...>` | Add/remove tags from thread. |
| `soothe agent list` | List available agents. |
| `soothe agent status` | Show detailed agent status. |

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show commands |
| `/exit`, `/quit` | Exit the TUI client while keeping daemon lifetime independent; in the Textual TUI, an active thread is stopped first after confirmation |
| `/detach` | Detach TUI and leave thread running (with confirmation if thread running); daemon keeps running |
| `/plan` | Show current plan tree |
| `/memory` | Show memory stats |
| `/context` | Show context stats |
| `/policy` | Show active policy profile |
| `/history` | Show recent prompt history |
| `/review` | Review recent conversation and action history |
| `/resume` | Resume a recent thread (interactive selection) |
| `/clear` | Clear the screen |
| `/config` | Show active configuration summary |
| `/thread` | Thread operations such as `list` and `archive <id>` |

**Note**: daemon lifetime is decoupled from client exit. `/detach` leaves work running. `/exit` and `/quit` exit the TUI client and preserve the daemon; the current Textual client stops an active thread first after confirmation, then detaches. Explicit daemon shutdown is handled by `soothe daemon stop`. See RFC-0013 for transport-level lifecycle semantics.

## TUI Widget Layout

The Textual TUI (`SootheApp`) uses a conversation-first layout with a docked footer stack:

```
+--------------------------------------------------------------+
| ConversationPanel                                            |
| [scrollable conversation history]                            |
| [user prompts and final assistant output]                    |
|                                                              |
+--------------------------------------------------------------+
| PlanTree (toggleable, hidden when inactive)                  |
+--------------------------------------------------------------+
| > ChatInput                                                  |
| [multi-line input with history navigation]                   |
+--------------------------------------------------------------+
| InfoBar: Thread / Events / Status                            |
+--------------------------------------------------------------+
```

### Widgets

- **ConversationPanel** — Main scrollable conversation surface implemented with `RichLog`. Displays user turns, resumed history, and surfaced assistant output.
- **PlanTree** — Toggleable plan display shown in the footer stack when relevant.
- **InfoBar** — Bottom status row with thread, event, and runtime state information.
- **ChatInput** — Multi-line `TextArea` input with UP/DOWN history navigation and auto-expanding height.

Activity and event rendering are handled by the RFC-0019 event processor and TUI renderer rather than by a standalone `ActivityInfo` widget.

### Keyboard Shortcuts

- `Ctrl+Q` — Quit TUI: Stop running thread and exit client (daemon keeps running, same as `/quit`)
- `Ctrl+D` — Detach TUI: Leave thread running and exit client (daemon keeps running, same as `/detach`)
- `Ctrl+C` (once) — Cancel currently running job
- `Ctrl+C` (twice within 1s) — Trigger `/quit` behavior (stop thread + exit with confirmation)
- `Ctrl+E` — Focus input field
- `Ctrl+Y` — Copy last message to clipboard
- `Ctrl+T` — Toggle plan tree visibility

**Key Behaviors**:
- **`Ctrl+Q` (`/quit`)**: Stops running thread (with confirmation), exits TUI, daemon keeps running
- **`Ctrl+D` (`/detach`)**: Leaves thread running (with confirmation), exits TUI, daemon keeps running
- **Double Ctrl+C**: First press cancels job; second press (within 1s) triggers quit behavior with confirmation

**Confirmation Dialogs**:
- If thread running and user presses `Ctrl+Q` or types `/quit`: "Thread {id} is running. Stop thread and exit? (y/n)"
- If thread running and user presses `Ctrl+D` or types `/detach`: "Thread {id} is running. Detach and leave it running? (y/n)"
- If thread idle: Exit immediately without confirmation

### Message Surfacing Rules

- ConversationPanel is intentionally low-noise:
  - Shows user turns and final main-assistant response text at end-of-turn.
  - Does not show streamed partial tokens, protocol events, tool activity, or subagent text.
- ActivityInfo is the progress surface:
  - Shows the last 5 lines of activity (protocol `soothe.*` events, tool call/result lines, subagent custom events, and subagent text summaries).
  - Applies `progress_verbosity` filtering (`minimal`, `normal`, `detailed`, `debug`) for both TUI and headless text output.
  - Browser progress is surfaced via structured `soothe.browser.step` events like other subagents.
  - Compact borderless display maximizes screen space for conversation.

### Activity Info Event Rendering

Events are rendered with type-specific formatting:

| Event | Type Pattern | Display Format |
|-------|-------------|---------------|
| Tool call | (messages mode) | `. Calling {tool_name}` (blue) |
| Tool result | (messages mode) | `> {tool_name}  {brief content}` (green) |
| Browser step | `soothe.browser.step` | `[browser] Step N: {action} @ {url}` |
| Subagent text | (messages mode) | `[subagent] Text: {brief summary}` |
| Research event | `soothe.research.*` | `[research] {label}: {query}` |
| Claude text | `soothe.claude.text` | `[claude] Text: {brief}` |
| Claude tool use | `soothe.claude.tool_use` | `[claude] Tool: {tool_name}` |
| Claude result | `soothe.claude.result` | `[claude] Done ($cost, duration)` |
| Skillify event | `soothe.skillify.*` | `[skillify] {label}: {skill}` |
| Weaver event | `soothe.weaver.*` | `[weaver] {label}: {agent_name}` |
| Protocol event | `soothe.{protocol}.*` | `{event_type}: {summary}` (policy includes `profile`) |

Verbose events are automatically truncated to ~80 chars for display. Full details are written to thread logs and the application log.

## Subagent Routing

Routing to subagents is primarily **LLM-driven** via the deepagents `task` tool. The main LLM decides when and how to delegate based on the user's request and available subagent descriptions.

### Available Subagents

| # | Name | Type | Description |
|---|------|------|-------------|
| 1 | Main | — | Orchestrator LLM |
| 2 | Planner | `SubAgent` | Structured planning and decomposition |
| 3 | Scout | `SubAgent` | Codebase exploration |
| 4 | Research | `CompiledSubAgent` | Multi-step web research |
| 5 | Browser | `CompiledSubAgent` | Browser automation |
| 6 | Claude | `CompiledSubAgent` | Claude Code integration |
| 7 | Skillify | `CompiledSubAgent` | Skill indexing and retrieval (RFC-0004) |
| 8 | Weaver | `CompiledSubAgent` | Task-specific agent generation (RFC-0005) |

### Routing Mechanism

The primary routing mechanism is the LLM's natural language understanding. When the main LLM receives a user request, it decides whether to handle it directly or delegate to a subagent via the `task` tool. This is the default and recommended approach.

**Deprecated**: Numeric prefix routing (e.g., `4 search quantum papers` to route to Research) was defined in `commands.py` but is **no longer used** in Soothe. The function `parse_subagent_prefix_from_input()` is retained for backward compatibility with external code but is not invoked in the main flow. Users should rely on natural language routing through the LLM instead.

## Subagent Memory Relay

### Intra-thread (within conversation)

Before delegation: `ContextProtocol.project_for_subagent(goal, token_budget)` builds a purpose-scoped, token-bounded briefing. The projection is injected into the subagent's task description. After return: `ContextProtocol.ingest(source=subagent_name, content=result)`.

RFC-0001 invariant 3: "Subagents receive a context projection scoped to their goal, NOT the orchestrator's full context."

### Inter-thread (across conversations)

After significant findings: `MemoryProtocol.remember(MemoryItem(source_thread=thread_id, ...))` — auto-stored for significant responses by `SootheRunner`. On new thread: `MemoryProtocol.recall(query)` retrieves relevant memories. Items carry `source_thread` for provenance.

## Logging Architecture

All logs are centralized under `$SOOTHE_HOME` (default `~/.soothe`):

| Path | Purpose |
|------|---------|
| `$SOOTHE_HOME/logs/soothe.log` | Application log (rotating, 10 MB, 3 backups) |
| `$SOOTHE_HOME/threads/{thread_id}.jsonl` | Thread logs (events, tool calls, conversation) |
| `$SOOTHE_HOME/history.json` | Input history |

### Thread Logging

`ThreadLogger` captures:
- **`kind: "event"`** — `soothe.*` custom events with a `classification` field (`protocol`, `subagent_custom`, `error`, `thinking`, `debug`) for structured filtering and audit replay
- **`kind: "tool_call"`** — Tool invocations from AIMessage (name, args preview)
- **`kind: "tool_result"`** — Tool results from ToolMessage (name, truncated content)
- **`kind: "conversation"`** — User and assistant turns (role, text)

In addition to thread JSONL records, all surfaced ActivityPanel and ConversationPanel lines are persisted in `soothe.log` as structured runtime logs for auditability.

### Subagent Logging Model

All subagents use `emit_progress()` from `soothe.utils.progress` for event emission. This function:
1. Writes the event to the LangGraph stream (for TUI/headless rendering)
2. Always logs at INFO level to the Python logger (for persistent file logging)

At "normal" verbosity, subagent events are suppressed from TUI/headless stdout -- only protocol events and errors display. Subagent events become visible at "detailed" verbosity. Persistent log files always record all events at INFO level.

### Third-Party Logger Suppression

`setup_logging()` centralises suppression of noisy third-party loggers (`httpx`, `httpcore`, `openai`, `anthropic`, `langchain_core`, `langgraph`, `browser_use`, `bubus`, `cdp_use`) to WARNING level. The browser subagent additionally suppresses browser-use-specific loggers to CRITICAL and redirects stdout/stderr during import.

Large content is automatically truncated (2000 chars for tool results, 500 for args) to keep logs manageable.

### Default Tools

Soothe ships with these default tools enabled out of the box:
- `datetime` — Current date/time (zero-dependency, no API key)
- `arxiv` — Academic paper search (langchain_community, no API key)
- `wikipedia` — Encyclopedia lookup (langchain_community, no API key)
- `websearch` — Web search using configured engines from config.yml (graceful degradation)

## Security

The TUI inherits PolicyProtocol enforcement. HITL interrupts from deepagents' `HumanInTheLoopMiddleware` are handled in the runner's interrupt loop. Initial implementation auto-approves; future versions can present approval prompts via the TUI.

## Dependencies

- RFC-0001 (System Conceptual Design)
- RFC-0002 (Core Modules Architecture Design)
- RFC-0006 (Context and Memory Architecture Design)

## Related Documents

- [RFC-0001](./RFC-0001.md) - System Conceptual Design
- [RFC-0002](./RFC-0002.md) - Core Modules Architecture Design
- [RFC-0006](./RFC-0006.md) - Context and Memory Architecture Design
- [RFC-0009](./RFC-0009.md) - DAG-Based Execution and Unified Concurrency
- [RFC Index](./rfc-index.md) - All RFCs
- [IG-007](../impl/007-cli-tui-implementation.md) - CLI TUI Implementation Guide
- [IG-010](../impl/010-tui-layout-history-refresh.md) - Textual TUI and Daemon Implementation
- [IG-017](../impl/017-progress-events-tools-polish.md) - Progress Events and Tools Polish
