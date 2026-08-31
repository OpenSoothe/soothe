# IG-770: ACP Server Location & Two-Direction Integration Analysis

**Implementation Guide**: IG-770
**Title**: ACP Server Location & Two-Direction Integration Analysis
**Status**: Draft
**Created**: 2026-08-31
**Dependencies**: RFC-000 (Invariant 8), IG-081 (Issue 2), §7b (Package Boundaries)
**Related**: `.soothe/plans/20260831T014156Z-per-users-chenxm-workspace-soothe-soothe-plans-2.md`

---

## Overview

This guide records the architectural analysis for where the ACP (Agent Client
Protocol) server lives in Soothe's package topology, and confirms the
two-direction integration design: **Soothe-as-Agent** (ACP-Server, callable by
external services/editors) and **Soothe-as-Client** (ACP-Client, calling
external ACP agents as remote subagents).

This completes step IZB-01 of the ACP implementation sequence. It is an
analysis-only deliverable — no runtime code changes are introduced here.
Subsequent implementation steps will follow the Changes section of the approved
plan.

---

## Decision: ACP-Server Location

### Ruling

**ACP-Server lives in the `soothe` host package as a stdio adapter, not inside
the `soothe-daemon` package and not as a standalone wrapper that reimplements
runtime.**

The `soothe-acp` binary is a thin stdio process that connects to a running
daemon via the existing WebSocket wire protocol (`soothe_sdk.wire`), translating
ACP `session/*` JSON-RPC methods into daemon `loop_input` / `loop_events` RPCs.
The adapter is a *client* of the daemon, using the same wire contracts as
`soothe-cli`.

### Why not inside `soothe-daemon`

The daemon already multiplexes channels (WebSocket, Discord, Telegram, Slack,
etc.) through `ChannelManager` and the `Channel` ABC. ACP *could* be registered
as a built-in daemon channel. However:

1. **§7b boundary rule**: `soothe_daemon` must not depend on
   `soothe_client` (the WS client) in runtime source. The daemon-backed ACP
   adapter needs the WS client to talk to the daemon — that import belongs in
   `soothe`, not `soothe_daemon`.
2. **Transport mismatch**: ACP's stable transport is stdio (JSON-RPC 2.0 over
   stdin/stdout). The daemon is WebSocket-native. A stdio shim that proxies to
   the daemon is the clean boundary — it does not force stdio handling into the
   daemon process model.
3. **Daemon is the single source of runtime truth.** ACP turns must flow
   through the same `LoopInputDispatcher` → `SootheRunner` → `EventBus` path as
   WebSocket turns, preserving durability, MCP session lifecycle, and
   StrangeLoop checkpointing. A wrapper that reuses the daemon's wire
   contracts guarantees this; an in-daemon channel that bypasses the wire layer
   would risk short-circuiting the normal plumbing.

### Why not a standalone wrapper that reimplements runtime

A standalone wrapper that boots its own StrangeLoop without the daemon would
lose multi-client durability, MCP session lifecycle, and the checkpoint graph.
The daemon-backed mode is primary. A standalone in-process mode is supported
as a secondary deployment option (boots `SootheDaemon` via
`bootstrap/entrypoint.run_daemon()` with ACP as the sole channel), but it is
not the launch requirement.

### Package placement

| Component | Package | Rationale |
|-----------|---------|-----------|
| ACP-Server adapter + `__main__` + console script | `packages/soothe` (`src/soothe/remote/acp/`) | Host-level remote-agent interop; `soothe` may import `soothe-sdk`/`soothe-nano` |
| ACP-Client adapter (`ACPRemoteAgent`) | `packages/soothe` (`src/soothe/remote/acp/client.py`) | Same — host-level |
| `agent-client-protocol` dependency | `packages/soothe/pyproject.toml` (optional `[acp]` extra) | Runtime dep of `soothe` only; not forced on `soothe-daemon`/`soothe-cli` |
| Transport dispatch hook (subagent resolver) | `packages/soothe/src/soothe/coreagent/builder.py` (host override) | Must NOT edit `soothe-nano` directly (DAG rule §7b); inject dispatch from host |
| Daemon-side ACP channel (standalone mode only) | `packages/soothe-daemon/src/soothe_daemon/channels/acp.py` | Only if standalone in-process mode is supported; daemon-backed mode needs no daemon changes |

---

## Two-Direction Integration

### Direction 1: ACP-Server (Soothe-as-Agent)

External services (Zed, Gemini CLI, other ACP clients) spawn `soothe-acp`
over stdio. The adapter translates ACP methods to daemon wire RPCs:

```
Editor/Service (Zed, Gemini CLI, other ACP client)
      │  stdio (JSON-RPC 2.0)
      ▼
soothe-acp binary  (packages/soothe/src/soothe/remote/acp/__main__.py)
      │
      ├── Daemon-backed mode: WS client → daemon wire protocol
      │   (soothe_sdk.wire → MessageRouter._handle_loop_input → LoopInputDispatcher)
      │
      └── Standalone mode: in-process SootheDaemon (bootstrap/entrypoint.run_daemon)
          with ACP as the sole stdio Channel
                  │
                  ▼
          ChannelManager → EventBus → SootheRunner → StrangeLoop
```

**Method translation map:**

| ACP method | Daemon wire RPC / path |
|------------|------------------------|
| `session/new` | `loop_subscribe` + `loop_input` (creates a loop/thread) |
| `session/prompt` | `loop_input` with content (enqueues a user turn) |
| `session/update` (notifications) ← daemon EventBus | `soothe.*` wire events: `agent_message_chunk`, `tool_call`, `plan` deltas |
| `session/cancel` | `cancel` RPC |
| `session/load` | daemon resume path (DurabilityProtocol / checkpoint replay) |
| `session/request_permission` ← Soothe | `PolicyProtocol` need-approval decisions |

**Event translation:** Soothe wire events are translated to ACP
`session/update` variants using `acp.helpers` builders (`text_block`,
`start_tool_call`, `update_tool_call`).

**Plan projection (lossy):** Soothe `Plan` is a DAG with dependencies and
concurrency policy. ACP plans are a flat list of `{content, priority, status}`.
The projection drops the dependency graph, keeping content/priority/status only.
This is acceptable for editor UX but must be documented in the adapter.

**Permission model bridge:** ACP `session/request_permission` is per-tool-call
and ad-hoc. Soothe `PolicyProtocol` is structured (category+action+scope,
`PermissionSet`). The adapter translates Soothe's structured decision into
ACP's single permission request and routes ACP client responses back.

**Capability advertisement:** ACP assumes the agent may use client fs/terminal.
Soothe has its own workspace tools. The adapter must NOT advertise client
fs/terminal capabilities; it keeps native tools only.

### Direction 2: ACP-Client (Soothe-as-Client)

Soothe delegates to external ACP agents (Gemini CLI, Claude Agent, Codex CLI)
as remote subagents, wrapped in the uniform `CompiledSubAgent` envelope
(RFC-000 Invariant 8 / Guiding Principle #9).

```
StrangeLoop subagent delegation
      │  SubagentConfig.transport == "acp"
      ▼
ACPRemoteAgent (packages/soothe/src/soothe/remote/acp/client.py)
      │  spawn_agent_process(endpoint)
      ▼
External ACP agent (Gemini CLI, Claude Agent, Codex CLI)
      │  session/* JSON-RPC over stdio
      ▼
CompiledSubAgent dict {name, description, runnable}
      │  (mirrors lazy_compiled_subagent_spec shape)
      ▼
task tool catalog (indistinguishable from local subagents)
```

**Resolver wiring:** The `transport` field already exists in
`SubagentConfig` (`soothe_nano/config/models.py:232`:
`transport: Literal["local", "acp", "a2a", "langgraph"] = "local"`) but is
currently ignored. The host `AgentBuilder`
(`packages/soothe/src/soothe/coreagent/builder.py`) injects a transport-dispatch
hook: when `transport == "acp"`, it routes to `ACPRemoteAgent` instead of the
default `SUBAGENT_FACTORIES`. The dispatch hook is injected from the host, not
added as an import in `soothe-nano` (DAG rule §7b: `soothe-nano` must not import
`soothe`).

**Lifecycle policy:** Long-running ACP agents may outlive a single delegation.
A session lifecycle policy (keep-alive vs per-call spawn) is needed.
Permission prompts from the remote agent must route back through Soothe's
`PolicyProtocol` or auto-approve per config.

---

## Design Principles

1. **Daemon is the single source of runtime truth.** ACP-Server must not bypass
   StrangeLoop, checkpointers, MCP registry, or EventBus. The daemon-backed
   mode ensures ACP turns flow through the same `LoopInputDispatcher` →
   `SootheRunner` → `EventBus` path as WebSocket turns.

2. **ACP-Server is a channel, not a new server.** It conforms to the `Channel`
   ABC (`channels/base.py`) like WebSocket/Discord/Telegram. The daemon already
   supports plugin channels via entry_points (`channels/registry.py:discover_plugins`);
   ACP-Server can register the same way or as a built-in.

3. **Wire contracts, not Python imports, cross the daemon boundary.** The ACP
   stdio entrypoint talks to the daemon via `soothe_sdk.wire` protocol frames —
   the same contracts `soothe-cli` uses. This respects §7b: the entrypoint
   (living in `soothe`) must not import `soothe_daemon` runtime source directly
   in the daemon-backed path; it uses the WS client.

4. **Two distinct adapters, one SDK.** ACP-Server (Soothe-as-Agent,
   editor-facing) and ACP-Client (Soothe-as-Client, subagent-facing) share the
   `agent-client-protocol` SDK but have different lifecycles, packages, and
   entry points.

5. **Preserve the Uniform Delegation Envelope (RFC-000 #9).** External ACP
   agents must be wrapped as `CompiledSubAgent` so callers cannot tell local
   from remote. This closes the gap explicitly deferred in IG-081 Issue 2.

6. **Build on the official SDK, don't reimplement JSON-RPC.** The
   `agent-client-protocol` package handles JSON-RPC 2.0 framing, schema
   validation, capability negotiation, and stdio lifecycle. Soothe's job is
   *adaptation*, not transport.

---

## Deployment Topology

Two deployment modes are supported from the same code path:

| Mode | Description | When to use |
|------|-------------|-------------|
| **Daemon-backed (primary)** | `soothe-acp` connects to a running daemon via WS wire protocol. No daemon code changes needed for transport — only the adapter + console script. | Production; preserves durability, MCP session lifecycle, multi-client. |
| **Standalone (secondary)** | `soothe-acp` boots an in-process `SootheDaemon` via `run_daemon()` with stdio as the sole channel. | Lightweight editor use; sacrifices multi-client durability. |

The daemon-backed mode is the primary recommendation. The standalone mode
requires a daemon-side ACP channel (`channels/acp.py`) and can be deferred if
standalone mode is not a launch requirement.

---

## Evidence

### Daemon channel architecture (confirmed)

- `channel_manager.py:25-73` — `ChannelManager` with `_channels` dict,
  `start_all()`, `stop_all()`.
- `channels/base.py:17-100` — `Channel` ABC with `start`/`stop`/`send`/
  `send_delta`.
- `channels/registry.py:57-91` — `discover_plugins` via entry_points group
  `soothe.channels` (ACP channel can register here).
- `server/core.py:884-896` — `ChannelManager(...)` constructed,
  `set_message_handler`, `start_all()` called in `start()`.
- `channel_manager.py:174-220` — `_build_channels()` builds WebSocket channel
  from config; ACP channel would be added here for standalone mode.

### ClientSession / ClientSessionManager (confirmed)

- `server/session.py:203-236` — `ClientSession` dataclass with `transport`,
  `transport_client`, `event_queue`, `sender_task`, `subscriptions`.
- `session.py:239-293` — `ClientSessionManager.create_session` subscribes to
  `_GLOBAL_TOPIC`.

### Daemon wire protocol entry (confirmed)

- `protocol/router.py:1948-2079` — `_handle_loop_input` RPC enqueues to
  `LoopInputDispatcher`.
- `server/handlers.py:91-107` — `_handle_client_message` validates and
  dispatches to `MessageRouter`.

### Standalone daemon boot path (confirmed)

- `bootstrap/entrypoint.py:23-41` — `run_daemon()` constructs `SootheDaemon`,
  runs `start()` + `serve_forever()`.

### SubagentConfig.transport stub (confirmed)

- `soothe_nano/config/models.py:232` —
  `transport: Literal["local", "acp", "a2a", "langgraph"] = "local"` — field
  exists, unimplemented.
- `soothe_nano/config/models.py:233` — `endpoint: str | None = None` — command
  path for the external ACP agent.

### Host AgentBuilder (confirmed)

- `packages/soothe/src/soothe/coreagent/builder.py:21-34` — `AgentBuilder`
  extends `nano_builder.AgentBuilder`; overrides
  `_filter_subagents_for_graph` and `_host_middleware_prefix`/`_suffix`. This is
  the injection point for the ACP transport-dispatch hook.

### No `remote/` directory exists (confirmed)

- `packages/soothe/src/soothe/` has no `remote/` subdir. `protocols/` contains
  only `runner.py` and `loop_working_memory.py` — no `RemoteAgentProtocol` stub
  exists in the host package (IG-005 planned `remote/` but it was never
  created).

### DAG rules (§7b, confirmed)

- `soothe` may import `soothe-sdk`/`soothe-nano`.
- `soothe-daemon` may import `soothe`/`soothe-autopilot`.
- `soothe-cli` sits above daemon and must not import it (uses WS wire
  contracts).
- The ACP stdio entrypoint in daemon-backed mode must use
  `soothe-client-python` (WS client), not Python imports into `soothe_daemon`.

### RFC-000 Invariant 8 gap (confirmed)

- `docs/specs/RFC-000-system-conceptual-design.md:175` — "Current deviation:
  remote agents accessed via direct protocol. Planned: wrap as
  `CompiledSubAgent` when ACP/A2A implementations are added."
- `docs/archive/impl/IG-081-rfc0001-compliance-fixes.md:106-140` — Issue 2
  documents the deferred gap; fix was to add the "Current deviation"/"Planned"
  hedging to RFC-000.

### Console script pattern (confirmed)

- `packages/soothe-daemon/pyproject.toml` — `soothed = "soothe_daemon.cli:app"`.
- `packages/soothe-cli/pyproject.toml` — `soothe`/`soothecli` scripts.
- `soothe-acp` follows the same pattern in `packages/soothe/pyproject.toml`.

### Wire contracts (confirmed)

- `packages/soothe-sdk/src/soothe_sdk/wire/` contains `protocol.py` (encode/
  decode/serialize), `codec.py`, `__init__.py`. The ACP adapter reuses
  `soothe_sdk.wire` protocol frames — the same contracts `soothe-cli` uses.

---

## Risks & Assumptions

- **ACP transport maturity**: Only stdio is stable; Streamable HTTP/WebSocket
  is a draft RFD. The daemon is WebSocket-native — a stdio shim proxying to the
  daemon is the safe path; do not block on the draft transport.
- **ACP v2 in draft**: Pin SDK version; design the adapter against
  `acp.PROTOCOL_VERSION`, not a hardcoded number.
- **Plan model lossiness**: ACP plans are a flat list of
  `{content, priority, status}`; Soothe plans are a DAG with dependencies and
  concurrency policy. The projection is lossy — ACP clients won't see dependency
  ordering. Acceptable for editor UX; document it.
- **Permission model mismatch**: ACP `session/request_permission` is
  per-tool-call, ad-hoc; Soothe `PolicyProtocol` is structured
  (category+action+scope, `PermissionSet`). The bridge must translate Soothe's
  structured decision into ACP's single permission request and route ACP client
  responses back.
- **Deployment topology**: The plan recommends daemon-backed as primary
  (preserves durability, MCP lifecycle, multi-client), standalone as secondary.
  This affects the entrypoint design and whether a daemon-side ACP channel is
  needed.

---

## Next Steps (Implementation)

This analysis is the prerequisite for the following implementation changes
(to be executed in subsequent steps, not in this guide):

1. Add `agent-client-protocol` optional dependency to
   `packages/soothe/pyproject.toml`.
2. Implement ACP-Server adapter (`packages/soothe/src/soothe/remote/acp/server.py`).
3. Implement ACP-Client adapter (`packages/soothe/src/soothe/remote/acp/client.py`).
4. Wire ACP transport into the subagent resolver via host `AgentBuilder` override.
5. Add ACP-Server stdio entrypoint + `soothe-acp` console script.
6. (Optional) Add ACP as a built-in daemon Channel for standalone mode.
7. Update RFC-000 Invariant 8 and IG-081 Issue 2 to close the deferred gap once
   ACP-Client wraps as `CompiledSubAgent`.

---

## RFC-000 Invariant 8 Status Update

This analysis confirms the path to closing Invariant 8's "Current deviation"
for ACP: once the ACP-Client adapter (`ACPRemoteAgent`) wraps external ACP
agents as `CompiledSubAgent` (Change 3 above), the uniform delegation envelope
is preserved and the deviation note can be removed.

The RFC-000 text is updated in this guide to reflect that the ACP direction is
now *analyzed and designed* (no longer "Planned" with no design). The full
deviation note is removed only when the ACP-Client implementation lands
(Change 3).
