# RFC-500: CLI TUI Architecture Design

**RFC**: 500
**Title**: CLI TUI Architecture Design
**Status**: Implemented
**Created**: 2026-03-12
**Updated**: 2026-03-28
**Related**: RFC-000, RFC-001, RFC-400, RFC-402

## Abstract

This RFC defines the architecture for Soothe CLI's interactive terminal user interface. The CLI provides three interaction modes: Textual TUI (default), headless CLI, and daemon-based background execution with attach/detach. The TUI builds on deepagents-canonical `astream()` pattern extended with protocol orchestration events.

## Interaction Modes

1. **Textual TUI (default)** — Full-featured interactive TUI connecting to daemon. Real-time streaming progress, protocol observability, thread management, dynamic subagent routing. Auto-starts daemon if not running.

2. **Headless CLI** — Single-prompt execution with streaming output to stdout/stderr. Supports `--format jsonl` for machine-readable events. No TUI required.

3. **Daemon-based background execution** — Daemon runs `SootheRunner` in background, serves events over WebSocket. Clients attach/detach/reconnect without losing session.

## Design Principles

1. **Native stream extension** — Consume deepagents-canonical `(namespace, mode, data)` 3-tuples from `agent.astream(stream_mode=["messages", "updates", "custom"], subgraphs=True)`. Protocol events extend as `custom` mode with `soothe.*` prefix.

2. **Protocol observability without coupling** — Protocols invoked before/after LangGraph stream. Activity surfaced as lightweight custom events (plain dicts). TUI renders as one-liner indicators. Protocols independent of presentation.

3. **Orchestration-layer runner** — `SootheRunner` between TUI and agent graph. Handles protocol orchestration (context projection, memory recall, plan creation, policy checks), thread lifecycle, yields unified stream. TUI is pure renderer.

## Architecture

```
CLI (ux/cli/main.py, Typer)
  └─ Entry point, config loading, command routing
Execution Surfaces
  └─ Textual TUI (ux/tui/app.py), Headless CLI (ux/cli/execution/*), daemon-backed flows
Daemon (daemon/server.py + transports/*)
  └─ SootheDaemon lifecycle, event routing, DaemonClient connections
SootheRunner (core/runner/*)
  └─ Protocol orchestration, LangGraph astream() pass-through, HITL interrupt loop, thread lifecycle
create_soothe_agent() -> CompiledStateGraph
  └─ deepagents middleware stack, subagents, tools, skills, protocol instances
Protocols (context, memory, planner, policy, durability)
```

## Stream Architecture

### Stream Format

LangGraph `(namespace, mode, data)` 3-tuple:

| Mode | Namespace | Content |
|------|-----------|---------|
| `messages` | `()` (main) | LLM text tokens, tool calls |
| `messages` | non-empty | Subagent text and tool calls |
| `updates` | `()` (main) | HITL interrupts |
| `custom` | `()` or non-empty | Subagent progress (`soothe.research.*`, `soothe.browser.*`) |
| `custom` | `()` (main) | Protocol orchestration events (`soothe.plan.*`, `soothe.policy.*`) |

**Naming**: `soothe.<component>.<action>`. Subagent: `soothe.<subagent>.<action>`, Protocol: `soothe.<protocol>.<action>`.

### Protocol Custom Events

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.thread.started/ended` | `thread_id`, `protocols` | Thread lifecycle |
| `soothe.context.projected/ingested` | `entries`, `tokens`, `source` | Context operations |
| `soothe.memory.recalled/stored` | `count`, `query`, `id`, `source_thread` | Memory operations |
| `soothe.plan.created/step_started/completed/failed` | `goal`, `steps`, `step_id`, `description`, `success`, `error` | Plan execution |
| `soothe.goal.batch_started/report` | `goal_ids`, `goal_id`, `step_count`, `completed`, `failed`, `summary` | Goal progress |
| `soothe.policy.checked/denied` | `action`, `verdict`, `profile`, `reason` | Policy enforcement |

### Event Rendering

For detailed rendering (two-level tool call trees, special tool behaviors, plan visualization), see **IG-053: CLI/TUI Event Progress Clarity**. Rendering is implementation-level, documented in IGs.

### Three-Phase Execution

**Phase 1: Protocol Pre-processing**
Thread management → Context restoration → Policy check → Context projection → Memory recall → Plan creation → Enriched input assembly.

**Phase 2: LangGraph Stream**
`agent.astream()` with `stream_mode=["messages", "updates", "custom"]`, `subgraphs=True`. HITL interrupt loop: collect `__interrupt__`, auto-approve, resume with `Command(resume=...)`. See RFC-200 for StepScheduler multi-step execution.

**Phase 3: Protocol Post-processing**
Context ingestion → Context persistence → Memory storage → Plan reflection → Thread persistence via `ThreadContextManager`.

## IPC Protocol

See **RFC-400: Unified Daemon Communication Protocol**.

### Transports

1. **WebSocket** (primary) — Default port `8765` (localhost), WebSocket text frames, all clients (CLI/TUI/web/desktop), real-time streaming.

2. **HTTP REST API** — Default port `8766` (localhost), HTTP/1.1 with JSON bodies, health checks, CRUD operations, management endpoints.

See RFC-400 for full protocol specification.

### WebSocket Messages

**Server → Client**: `event` (stream chunk), `status` (daemon state), `command_response`, `subscription_confirmed`, `error`.

**Client → Server**: `input` (user message), `command` (slash command), `detach`, `resume_thread`, `subscribe_thread`, `new_thread`.

## CLI Commands

Pattern: `soothe <subcommand> <action> [options]`

**Main**: `soothe` (TUI), `soothe -p "prompt" --no-tui` (headless), `soothe autopilot run "task"` (autonomous).

**Daemon**: `soothe-daemon start/stop/status/restart [--foreground]`.

**Thread**: `soothe thread list/show/continue/archive/delete/export/stats/tag`.

**Config**: `soothe config show/init/validate`.

**Agent**: `soothe agent list/status`.

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show commands |
| `/exit`, `/quit` | Exit TUI, stop thread (with confirmation if running), daemon keeps running |
| `/detach` | Detach TUI, leave thread running (with confirmation if running), daemon keeps running |
| `/plan` | Show current plan tree |
| `/memory` | Show memory stats |
| `/context` | Show context stats |
| `/policy` | Show active policy profile |
| `/history` | Show recent prompt history |
| `/review` | Review conversation/action history |
| `/resume` | Resume recent thread (interactive) |
| `/clear` | Clear screen |
| `/config` | Show active configuration |

**Daemon Lifetime**: Decoupled from client exit. `/detach` leaves work running. `/exit`/`/quit` stop thread then exit TUI, daemon persists. Explicit shutdown via `soothe-daemon stop`.

## TUI Layout

```
+--------------------------------------------------------------+
| ConversationPanel (scrollable history, user/assistant turns) |
+--------------------------------------------------------------+
| PlanTree (toggleable, hidden when inactive)                  |
+--------------------------------------------------------------+
| > ChatInput (multi-line, history navigation)                 |
+--------------------------------------------------------------+
| InfoBar: Thread / Events / Status                            |
+--------------------------------------------------------------+
```

**Widgets**: `ConversationPanel` (RichLog), `PlanTree` (toggleable), `InfoBar` (status), `ChatInput` (TextArea with history).

### Keyboard Shortcuts

- `Ctrl+Q` — Quit: Stop thread + exit (with confirmation if thread running)
- `Ctrl+D` — Detach: Leave thread running + exit (with confirmation)
- `Ctrl+C` (once) — Cancel current job
- `Ctrl+C` (twice within 1s) — Trigger quit with confirmation
- `Ctrl+E` — Focus input
- `Ctrl+Y` — Copy last message
- `Ctrl+T` — Toggle plan tree

### Message Surfacing

**ConversationPanel**: User turns, final assistant response text. No partial tokens, protocol events, tool activity, subagent text.

**ActivityInfo**: Last 5 lines of activity (protocol events, tool calls, subagent events). `VerbosityTier` filtering (RFC-501). Browser progress via `soothe.browser.step` events.

## Subagent Routing

**Primary**: LLM-driven via deepagents `task` tool. Main LLM decides delegation based on request and subagent descriptions.

**Available**: Main (orchestrator), Planner, Scout, Research (RFC-601), Browser, Claude, Skillify (RFC-601), Weaver (RFC-601).

**Deprecated**: Numeric prefix routing (e.g., `4 search...` → Research). Retained for compatibility but not used in main flow. Use natural language routing.

## Memory Relay

**Intra-thread**: Before delegation: `ContextProtocol.project_for_subagent(goal, token_budget)`. After return: `ContextProtocol.ingest(source=subagent_name, content=result)`.

**Inter-thread**: After significant findings: `MemoryProtocol.remember()`. On new thread: `MemoryProtocol.recall(query)`. Items carry `source_thread` for provenance.

## Logging

**Paths**: `$SOOTHE_HOME/logs/soothe.log` (application, rotating 10 MB), `$SOOTHE_HOME/threads/{thread_id}.jsonl` (thread events), `$SOOTHE_HOME/history.json` (input history).

**ThreadLogger**: `kind: "event"` (soothe.* events with classification), `kind: "tool_call"`, `kind: "tool_result"`, `kind: "conversation"`.

**Subagent Logging**: `emit_progress()` writes to LangGraph stream + Python logger (INFO level). At "normal" verbosity, subagent events suppressed from TUI/stdout. Visible at "detailed". Log files always record all events.

**Suppression**: Third-party loggers (`httpx`, `openai`, `langchain_core`, etc.) → WARNING. Browser subagent suppresses browser-use loggers → CRITICAL.

**Truncation**: Tool results (2000 chars), args (500 chars).

## Security

TUI inherits `PolicyProtocol` enforcement. HITL interrupts from `HumanInTheLoopMiddleware` handled in runner interrupt loop. Current: auto-approve. Future: approval prompts via TUI.

## References

- RFC-000: System conceptual design
- RFC-001: Core modules architecture
- RFC-400: Context protocol architecture
- RFC-402: Memory protocol architecture
- RFC-201: Unified AgentLoop execution (replaces deprecated RFC-202)
- RFC-450: Unified daemon communication
- RFC-501: VerbosityTier unification

---

*CLI TUI architecture with three interaction modes, protocol observability, daemon-based execution, and daemon-client decoupled lifetime.*