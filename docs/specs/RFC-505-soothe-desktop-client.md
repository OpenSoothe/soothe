# RFC-505: Soothe Desktop Client Architecture

**RFC**: 505
**Title**: Soothe Desktop Client Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-04
**Last Updated**: 2026-06-04
**Dependencies**: RFC-403 (Unified Event Naming), RFC-450 (Daemon Communication Protocol), RFC-454 (Slash Commands), RFC-500 (CLI/TUI Architecture), RFC-503 (Loop-First UX), RFC-504 (Loop Management Commands)
**Supersedes**: ---
**Author**: brainstormed via platonic-brainstorming, formalized from `docs/drafts/2026-06-04-soothe-desktop-design.md`

---

## 1. Abstract

This RFC defines the architecture of **soothe-desktop**, a Mac-first Electron + React desktop client that connects to a user-managed `soothed` over WebSocket and reuses the existing `soothe-client-typescript` package as its protocol layer. The desktop client owns UI and process management only; it adds no new daemon-side capabilities and respects RFC-450 transport, RFC-503 loop-first semantics, and RFC-403 event taxonomy without modification.

The first release (v1, MVP) ships a single-window multi-tab chat experience with streaming reasoning/tool cards, an inline clarification (`ask_user`) widget, slash command palette with skill invocation, file-change diff cards, image attachments, and a sidebar of persisted loops. Higher-surface features (model picker, MCP viewer, autopilot dashboard, loop-tree visualization, multi-window) are explicitly deferred to v1.1+.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* The process-architecture split between Electron **main** (Node) and **renderer** (browser) and the rationale for placing the WebSocket connection in main.
* The **tab-per-loop** UX model and its mapping to the daemon's `loop_subscribe` invariant of one client per loop.
* The **renderer event-rendering pipeline** keyed by RFC-403 event types, with a typed registry and a fallback renderer for unknown types.
* The **IPC contract** (channel names, request/response payloads, push events) bridging renderer and main.
* The **clarification (`ask_user`) resume flow** at the renderer layer, mirroring TUI semantics introduced in commit `45917adb`.
* The **module layout** of the `apps/soothe-desktop` submodule and how it consumes `client/typescript` as a `file:` dependency.

### 2.2 Non-Goals

This RFC does **not** define:

* Concrete React component signatures or TypeScript type definitions (those belong in the implementation guide).
* New daemon-side RPCs, event types, or protocol changes — soothe-desktop is purely a client of the contracts in RFC-450 and RFC-403.
* Authentication or transport security beyond what the daemon currently enforces (localhost trust + CORS allowlist).
* Auto-update, telemetry, crash reporting, or release engineering.
* Multi-window orchestration or per-window-isolated daemon connections.
* Bundling or auto-spawning of `soothed`; v1 assumes the user manages the daemon process.
* Replacement of the existing CLI/TUI — both clients coexist and remain first-class.

---

## 3. Background & Motivation

### 3.1 Existing user surface

Soothe today ships two first-class clients:

* **`soothe` CLI** (`packages/soothe-cli`) — Typer entry point, headless one-shot mode (`-p`), and a Textual TUI default.
* **`soothed` daemon** (`packages/soothe-daemon`) — single ASGI app serving WebSocket at `/`, default `ws://127.0.0.1:8765`.

The TUI is **single-loop** (one active subscription per process), terminal-bound, and renders streaming events into a single scrollback. It already implements: streaming reasoning cards, tool cards with collapsible activity, file-change preview, inline clarification widget, slash command palette with skill invocation, image attachments, modal screens for model/theme/MCP/autopilot.

### 3.2 Why a desktop client

Several use cases are uneven or impossible in the TUI:

* **Multi-loop monitoring** — users running 24/7 autonomous loops want to peek at one loop while another runs; the TUI's single-subscription model forces serial attention.
* **Rich diffs** — file-change cards in the TUI are text-only; a GUI can render syntax-highlighted side-by-side diffs.
* **Drag-and-drop attachments** — TUI requires terminal paste support that varies by emulator; a desktop window is natively drag-targetable.
* **Discoverability** — point-and-click loop history beats `soothe loop list` for users who want to browse their work.

### 3.3 Why Electron + React, why reuse the TS client

* **Electron + React** matches the reference UX (Codex / Claude Code style) and gives access to a large UI-component ecosystem (shadcn/ui, Radix).
* **Reusing `soothe-client-typescript`** (already a working WebSocket client; tested at `client/typescript/test/`) means the desktop owns zero protocol code. The client tracks RFC-450 wire changes automatically as the client package is bumped.
* The TS client imports Node `ws` and therefore must run in a Node context — the Electron **main** process — not in a browser-context renderer.

---

## 4. Architecture Overview

### 4.1 System Context

```
┌──────────────────────────────────────────────────────────────────┐
│ soothe-desktop (Electron application)                            │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Renderer (Chromium, sandboxed)                             │  │
│  │  React UI · zustand state · Tailwind/shadcn primitives     │  │
│  └─────────────────────────┬──────────────────────────────────┘  │
│                contextBridge IPC (typed)                          │
│  ┌─────────────────────────┴──────────────────────────────────┐  │
│  │ Main (Node)                                                │  │
│  │  WSManager (Map<tabId, Client>) · DaemonHealth · Settings  │  │
│  └─────────────────────────┬──────────────────────────────────┘  │
└────────────────────────────│─────────────────────────────────────┘
                  WebSocket (ws://127.0.0.1:8765)
┌────────────────────────────┴─────────────────────────────────────┐
│ soothed (user-managed; RFC-450)                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Diagram

```
+------------------- Renderer (React) -------------------+
| AppShell                                               |
|   ├── LoopsSidebar      (loops:list polling on focus)  |
|   ├── TabBar            (status badges per tab)        |
|   ├── TabView (current tab)                            |
|   │     ├── ChatScroll  (virtuoso-windowed)            |
|   │     │     └── EventCard[]  (registry-resolved)     |
|   │     └── Composer    (textarea + slash + atts)      |
|   └── CommandPalette · SettingsDialog · EmptyState     |
+--------------------------------------------------------+
                          ▲ ▼ IPC
+--------------------- Main (Node) ----------------------+
| IPC handlers (tab, loops, daemon, settings)            |
| WSManager — one `Client` per open tab                  |
| DaemonHealth — periodic checkDaemonStatus probe        |
| Settings — electron-store (daemon URL, theme)          |
+--------------------------------------------------------+
                          ▲ ▼ WebSocket
+--------------------- soothed --------------------------+
+--------------------------------------------------------+
```

---

## 5. Components

### 5.1 Renderer

**Responsibility**: present streaming loop activity, accept user input, and translate UI events into IPC calls. Holds no socket state; all daemon I/O is mediated by main.

* **AppShell** — three-region layout (sidebar · tab bar · main pane). Per-tab views are mounted/unmounted as tabs open/close; per-tab state lives in zustand keyed by `tabId` and is retained while the tab exists.
* **LoopsSidebar** — calls `loops:list` on focus and on tab lifecycle events. Renders persisted loops grouped by status (active, idle, archived). Right-click → Delete invokes `tab:close` with `mode: "delete"` if the loop is open, otherwise direct `loops:delete`.
* **TabBar** — one tab per open loop. Tab title shows the loop's first user message (truncated) or the daemon-assigned identifier; status indicator reflects the latest `tab:status` push (`connecting` · `ready` · `reconnecting` · `error`) merged with derived UI state (running spinner, idle dot, amber clarification badge).
* **ChatScroll** — `react-virtuoso` windowed list of `EventCard` components. The card emitted for a daemon event is resolved via the renderer registry (§5.3).
* **Composer** — textarea, attachment strip, slash command palette (shadcn/cmdk). See §6.
* **CommandPalette** — global `Cmd/Ctrl+K` palette listing actions (open settings, new chat, switch tab, invoke skill).
* **State** — single zustand store, sliced by concern (`tabs`, `loops`, `events`, `settings`, `clarification`). Event slice is `Map<tabId, EventLogEntry[]>`; append-only with windowed render.

### 5.2 Main

**Responsibility**: own all WebSocket connections, persist user settings, supervise daemon health, and forward decoded events to the renderer.

* **WSManager** — `Map<tabId, Client>` where each `Client` is the `soothe-client-typescript` instance. Per-tab lifecycle:
  1. `tab:open` → instantiate `Client(url)`, `connect()`, wait `daemon_ready`, then either `loop_new` or `loop_reattach`.
  2. Subscribe with `verbosity: "full"`, `stream_delivery: "adaptive"`.
  3. Bridge the client's `'message'` events to renderer pushes on `tab:event` channel, tagged with `tabId`.
  4. On `tab:close` mode `detach` → `sendLoopDetach` then `close()`; mode `delete` → `deleteLoop` then `close()`.
  5. On disconnect → emit `tab:status` `reconnecting`, attempt `connectWithRetries` (existing helper in `client/typescript/src/session.ts`); on success replay subscription via `loop_reattach`.
* **DaemonHealth** — periodic `checkDaemonStatus` probe (every 5s when no tab is open, every 30s with tabs open). Result feeds `daemon:health` responses and the EmptyState screen.
* **Settings** — `electron-store` for `daemonUrl` (default `ws://127.0.0.1:8765`), `theme` (`light` | `dark` | `system`), `windowBounds`. No secrets stored; daemon has no auth.
* **IPC handlers** — thin adapters around WSManager / DaemonHealth / Settings, registered via `ipcMain.handle` for request/response channels and `webContents.send` for push channels.

### 5.3 Event Renderer Registry

**Responsibility**: resolve a daemon event to a React component without coupling to specific event modules.

* **Registry shape**: `Record<EventTypePattern, FC<EventCardProps>>` where `EventTypePattern` is either a full event `type` string or a glob over RFC-403 segments (`soothe.tool.execution.*`).
* **Resolution order**: exact match → most-specific glob → fallback `DebugCard`.
* **Fallback policy**: unknown event types render a small collapsed debug card (timestamp · type · JSON preview), never silently dropped. This protects forward-compatibility as the daemon adds events.
* **MVP renderers**:

  | Renderer | Source event family |
  | --- | --- |
  | `AssistantBubble` | streamed `AIMessage` text chunks coalesced per turn |
  | `ReasoningCard` (collapsed) | `soothe.cognition.agent_loop.*`, `soothe.cognition.plan.*` |
  | `ToolCard` (collapsible activity) | `soothe.tool.execution.{started,completed,error}` |
  | `DiffCard` | file-edit wire frames (see §8.3) |
  | `SubagentChip` | `soothe.subagent.<agent>.<signal>` |
  | `ClarificationCard` | `soothe.loop.clarification.{requested,answered,deferred}` |
  | `ErrorBanner` | `soothe.error.*` + envelope `{type:"error"}` |
  | `FinalReportCard` | terminal `AgenticStepCompletedEvent` |
  | `DebugCard` (fallback) | anything else |

### 5.4 IPC Bridge

**Responsibility**: enforce that the only renderer-visible Node surface is a typed `window.soothe` object exposed via `contextBridge.exposeInMainWorld`. Node integration in the renderer is **disabled**; context isolation is **enabled**.

---

## 6. Data Flow

### 6.1 Primary Flow: User sends a prompt on an existing tab

```
User types in Composer ──► renderer.tabSlice.queueInput
                              │
                              ▼
                  ipc.send('tab:input', {tabId, text, attachments?})
                              │
                              ▼
        Main: WSManager.get(tabId).sendInput(text, {loopID, attachments})
                              │
                              ▼
                  WebSocket → soothed (loop_input frame)
                              │
                              ▼
                  daemon emits stream of `soothe.*` events
                              │
                              ▼
        Main: Client 'message' handler ──► ipc.send('tab:event', {tabId, event})
                              │
                              ▼
       Renderer: eventSlice.append(tabId, event) ──► ChatScroll re-renders
                              │
                              ▼
       EventRegistry resolves event.type → renders card
```

### 6.2 Tab open (new loop)

```
"New chat" ──► tab:open {} ──► main: client.connect(); sendLoopNew(); waitForLoopNewResponse;
                                       sendLoopSubscribe(loopId, "full", "adaptive");
                                       waitForSubscriptionConfirmed;
                                       respond {tabId, loopId}
              ──► renderer creates TabView; eventSlice opens empty log
```

### 6.3 Tab open (reattach existing loop)

```
Sidebar click ──► tab:open {loopId} ──► main: client.connect(); sendLoopReattach(loopId);
                                                consume history_replay frames →
                                                ipc.send('tab:event', ...) for each;
                                                emit ipc.send('tab:status', 'ready') when
                                                history_replay_complete arrives.
              ──► renderer appends each replayed event in order; scroll auto-pinned to bottom.
```

### 6.4 Clarification resume

```
Daemon: emits soothe.loop.clarification.requested
   │
   ▼
Main: forwards as tab:event
   │
   ▼
Renderer: registry resolves ClarificationCard; clarificationSlice.set(tabId, pending);
          tab title shows amber badge; "stream ended" suppression flag set.
   │
   ▼
User: types answers, submits
   │
   ▼
Renderer: ipc.send('tab:input', {tabId, text, clarificationAnswer: true,
                                  intentHint: "resume_clarification"})
   │
   ▼
Main: client.sendInput(synthesizedText, {loopID, ...flags exposed in InputOptions})
   │
   ▼
Daemon: emits soothe.loop.clarification.answered + step_completed; loop resumes.
   │
   ▼
Renderer: ClarificationCard resolves; clarification slice clears; badge cleared.
```

---

## 7. Invariants and Constraints

### 7.1 Architectural Invariants

| Invariant | Meaning | Consequence of Violation |
|-----------|---------|--------------------------|
| WS-in-main | All `Client` instances live in the Electron main process. | Renderer would need Node integration → security regression; CORS issues; reconnect logic duplicated. |
| One-Client-per-tab | Each open tab owns exactly one `Client` and exactly one loop subscription. | Daemon enforces `_client_subscribed_loop_id`; sharing a Client across tabs would force serial subscriptions and lose multi-loop concurrency. |
| Protocol-passthrough | Desktop adds no new event types, RPCs, or wire fields. All daemon I/O conforms to RFC-450 / RFC-403. | Forking the protocol creates a fragile second wire spec to maintain. |
| Registry-fallback-required | Every event must render *something*; unknown event types fall back to `DebugCard`. | Silent event drops mask daemon-side regressions and confuse users. |
| Renderer-stateless-WS | Renderer holds zero socket handles. State is rehydrated from `tab:status` + replayed `tab:event` pushes. | Renderer reload (HMR or crash) would orphan sockets and leak subscriptions. |
| Loop-keep-alive-on-close | Closing a tab issues `loop_detach`, not `loop_delete`, unless the user explicitly requests delete. | Accidental deletion of long-running autonomous loops. |

### 7.2 Dependency Constraints

| Constraint | Rule |
|------------|------|
| TS client version | Pinned via `file:../../client/typescript`; bumped when the daemon protocol bumps. |
| Daemon CORS | Renderer Origin must match `transport.websocket.cors_origins` (default `http://localhost:*`, `http://127.0.0.1:*`). The Electron renderer uses a `file://` Origin in production; main proxies WebSocket so Origin matches main's Node context, not the renderer. |
| Daemon transport | WebSocket only (RFC-450 / RFC-0013); no Unix sockets, no bare TCP. |
| Authentication | None. v1 inherits localhost-trust posture. Any future auth must be added daemon-side first. |

---

## 8. Abstract Schemas

### 8.1 IPC Channels

| Channel | Direction | Request payload | Response / push payload |
|---------|-----------|-----------------|-------------------------|
| `daemon:health` | renderer→main, req/resp | `{}` | `{live: bool, version?: string, error?: string}` |
| `loops:list` | renderer→main, req/resp | `{filter?, limit?}` | `LoopListResponse` (per RFC-450) |
| `loops:delete` | renderer→main, req/resp | `{loopId}` | `LoopDeleteResponse` |
| `tab:open` | renderer→main, req/resp | `{loopId?}` | `{tabId, loopId}` |
| `tab:input` | renderer→main, fire | `{tabId, text, attachments?, clarificationAnswer?, intentHint?, modelOverride?}` | — |
| `tab:command` | renderer→main, fire | `{tabId, cmd}` | — |
| `tab:close` | renderer→main, fire | `{tabId, mode: "detach"\|"delete"}` | — |
| `tab:event` | main→renderer, push | — | `{tabId, event: DecodedDaemonEvent}` |
| `tab:status` | main→renderer, push | — | `{tabId, state: "connecting"\|"ready"\|"reconnecting"\|"error", error?: string}` |
| `settings:get` | renderer→main, req/resp | `{key?}` | `Settings` partial |
| `settings:set` | renderer→main, req/resp | `Partial<Settings>` | `Settings` |

### 8.2 Tab Lifecycle State

| Field | Type | Description |
|-------|------|-------------|
| `tabId` | string (uuid) | Renderer-assigned, stable for the tab's lifetime. |
| `loopId` | string | Daemon loop id; assigned on `loop_new` or supplied for reattach. |
| `status` | enum | `connecting` · `ready` · `reconnecting` · `error` (mirrors `tab:status` pushes). |
| `clarificationPending` | bool | True while a `clarification.requested` is outstanding for this tab. |
| `attachments` | `Attachment[]` | Composer-staged attachments not yet sent. |
| `eventLog` | `EventLogEntry[]` | Append-only ordered log, persisted to memory only. |

### 8.3 Attachment

| Field | Type | Description |
|-------|------|-------------|
| `filename` | string | Original filename (or generated `pasted-image-<ts>.png`). |
| `mimeType` | string | e.g. `image/png`. |
| `base64` | string | Raw payload; main forwards to `loop_input.attachments[]` per existing TUI shape. |

### 8.4 Settings

| Field | Type | Default |
|-------|------|---------|
| `daemonUrl` | string | `ws://127.0.0.1:8765` |
| `theme` | enum | `system` |
| `windowBounds` | `{x,y,w,h}` | last seen |

---

## 9. Relationship to Other RFCs

| RFC | Relationship |
|-----|--------------|
| RFC-403 (Unified Event Naming) | Event renderer registry keys are RFC-403 type strings; fallback policy preserves forward compatibility. |
| RFC-450 (Daemon Communication Protocol) | All main↔daemon wire I/O conforms to RFC-450; no new wire types added. |
| RFC-454 (Slash Commands) | Slash palette consumes the same command list semantics; skill invocation uses `invoke_skill` per RFC-454. |
| RFC-500 (CLI/TUI Architecture) | Soothe-desktop is a peer client; both consume the same daemon contracts. No code shared. |
| RFC-503 (Loop-First UX) | Tab-per-loop model is the desktop expression of loop-first semantics; reattach uses `loop_reattach` history replay. |
| RFC-504 (Loop Management Commands) | Sidebar consumes `loop_list`, `loop_get`, `loop_delete`; CLI parity for non-tabbed loop management. |

---

## 10. Open Questions

1. **CORS Origin for Electron renderer** — main process opens the WebSocket so the Origin header is Node's, not the renderer's `file://`. Confirm `cors_origins` default accepts main's Origin (or document the required allowlist entry) before first beta.
2. **Renderer hot-reload during dev** — verify reattach-on-renderer-reload doesn't double-subscribe (main's WSManager must be the source of truth and tear down orphaned tabs).
3. **Workspace dependency vs `file:` link** — `file:` is fine for the MVP but causes lockfile churn when `client/typescript` is bumped. Revisit if a second TS package lands.
4. **Per-tab vs shared health probe** — currently a single DaemonHealth probe. If multi-window arrives in v1.1, decide whether each window owns its own probe.
5. **Streaming text coalescing** — daemon emits `AIMessageChunk` frames; whether to coalesce at main or renderer affects re-render rate. Recommend renderer-side using `react-virtuoso`'s `followOutput`.

---

## 11. Conclusion

Soothe-desktop is a thin Electron+React presentation layer over the existing daemon protocol. By delegating all wire concerns to `soothe-client-typescript` and constraining renderer responsibilities to UI and per-tab state, the v1 design avoids forking the protocol, isolates security-sensitive Node code in main, and ports the established TUI interaction patterns (clarification widget, slash palette, image attachments) to a multi-tab GUI form factor. The MVP scope is deliberately narrow — chat + history + clarification + diffs + attachments — to ship a usable desktop in a single milestone; modal-heavy features (model picker, MCP viewer, autopilot dashboard, loop-tree visualization) defer to v1.1 once the core flow is validated.

Implementation will follow as an Implementation Guide under `docs/impl/`, decomposed into milestones: (M1) main+IPC+health, (M2) tab lifecycle + chat streaming, (M3) clarification + composer, (M4) diffs + attachments, (M5) packaging.
