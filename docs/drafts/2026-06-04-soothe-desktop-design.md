# Soothe Desktop App — v1 Design

## Context

Soothe today ships a Python CLI + Textual TUI (`packages/soothe-cli`) that talks to a separate `soothed` daemon over WebSocket. The TUI is single-loop, terminal-bound, and uneven for users who want a Codex- or Claude-Code-style GUI experience (rich diffs, drag-and-drop attachments, multi-tab background loops, point-and-click history browsing).

This design bootstraps `apps/soothe-desktop` — a fresh git submodule (currently only `LICENSE`) — into an **Electron + React desktop app**. It reuses the existing TypeScript daemon client at `client/typescript` (`soothe-client-typescript`, WebSocket over Node `ws`) so the desktop only owns UI and process management, not protocol code.

**Outcome**: a Mac-first Electron app that lets a user open multiple Soothe loops as tabs, watch their reasoning/tool activity live, answer agent clarification questions inline, and review file-edit diffs — all backed by a `soothed` they manage themselves.

## Scope

### v1 (MVP) — in scope

- Connect to a user-managed `soothed` over WebSocket; first-run empty state when unreachable with copy-pasteable `soothed start` and Retry.
- Multi-tab single-window UI: one tab = one subscribed loop, sidebar lists all persisted loops.
- Streaming chat with **reasoning + tool cards** (collapsible), **clarification inline widget** (ask_user resume flow), **slash command palette + skill invocation**, **file-change diff cards**, **image attachments** (paste/drag-drop).
- Settings: daemon URL/port, theme (light/dark/system).
- Reattach to existing loops with `history_replay` consumed into the chat scroll.
- Tab close = `loop_detach` (loop keeps running); sidebar right-click → Delete = `loop_delete`.

### Deferred (v1.1+, explicitly out of scope)

Model picker · MCP viewer · Autopilot dashboard · Loop-tree visualization · Notifications/system tray · Auto-update · Multi-window · Authentication (daemon has none; localhost trust).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Renderer  (React + Vite + Tailwind + shadcn/ui + zustand)   │
│   App shell · Sidebar · TabBar · Chat · Composer ·         │
│   Command palette · Clarification widget · Diff cards       │
└──────────────────────────┬──────────────────────────────────┘
                contextBridge (typed IPC channels)
┌──────────────────────────┴──────────────────────────────────┐
│ Main process (Node)                                          │
│   WSManager — one soothe-client-typescript Client per tab    │
│   DaemonHealth prober · electron-store settings · windowing │
└──────────────────────────┬──────────────────────────────────┘
                       WebSocket
┌──────────────────────────┴──────────────────────────────────┐
│ soothed @ ws://127.0.0.1:8765 (user-managed)                 │
└─────────────────────────────────────────────────────────────┘
```

**WS lives in main, not renderer**, because: (a) `soothe-client-typescript` imports Node `ws`; (b) daemon CORS allowlist (`http://localhost:*`, `http://127.0.0.1:*`) is awkward for Electron renderer Origins; (c) main can hold connections across renderer reloads and centralize reconnect/health logic.

**One `Client` per tab**, not a shared multiplexed connection, because the daemon enforces "one client = one subscribed loop" (`_client_subscribed_loop_id`, `packages/soothe-daemon/src/soothe_daemon/protocol/router.py:129`). Multiple concurrent loops therefore need multiple connections.

## Multi-tab loop model

- Opening a sidebar entry → main spawns a new `Client`, calls `loop_reattach`, streams `history_replay` frames + live events back to the renderer keyed by `tabId`.
- "New chat" → main calls `loop_new`, then `loop_subscribe` with `verbosity: "full"`, `stream_delivery: "adaptive"`.
- Tab title encodes status: spinner (`running`), grey dot (`idle`), amber badge (clarification pending). Switching focus does **not** detach background loops.
- Close tab → `loop_detach` (keeps loop alive on daemon). Sidebar Delete → `loop_delete` (permanent).

## Event rendering pipeline

Single typed registry, `Record<string, FC<EventCardProps>>`, keyed by the daemon event `type` (`soothe.<domain>.<component>.<action>` per `packages/soothe-sdk/src/soothe_sdk/core/events.py`). Unknown types fall back to a compact debug card so new event types added daemon-side never silently disappear.

Built-in renderers for MVP:

| Renderer | Event families |
| --- | --- |
| Assistant markdown bubble | final `AIMessage` chunks |
| Reasoning / plan card (collapsed) | `soothe.cognition.strange_loop.*`, `soothe.cognition.plan.*` |
| Tool card (collapsible activity preview) | `soothe.tool.execution.{started,completed,error}` |
| File-change diff card | file-edit wire frames (mirrors `tui/widgets/file_change_preview.py`) |
| Subagent progress chip | `soothe.subagent.<agent>.<signal>` |
| Clarification inline widget | `soothe.loop.clarification.{requested,answered,deferred}` |
| Error banner | `soothe.error.*` + envelope `{type:"error"}` |

Per-tab event log lives in zustand with windowed rendering (`react-virtuoso`) so multi-hour sessions stay responsive.

## Composer

- Bottom-anchored textarea + slash palette (shadcn/cmdk).
- Slash command source = static MVP list (`/clear`, `/cancel`, `/exit`, `/quit`) ∪ dynamic `skills_list` results as `/skill:<name>` entries (refreshed on tab open).
- Image attachments: paste, drag-drop, file picker. Stored as `{filename, mimeType, base64}` and sent via `loop_input.attachments` (matches `tui/textual_adapter.py:1609-1623`).
- Keymap: `Enter` send · `Shift+Enter` newline · `Esc` interrupt (`/cancel`) · `Cmd/Ctrl+K` command palette · `Shift+Tab` toggle clarification mode (mirrors TUI).

## Clarification (ask_user) flow

Wired end-to-end to match recent daemon behavior (commit `45917adb`):

1. Main forwards `soothe.loop.clarification.requested` event to renderer with `{questions, origin_node, mode, step_id}`.
2. Renderer mounts inline `ClarificationCard` (one input per question) at the position of the running step card; tab title shows amber badge.
3. On submit, renderer → main `tab:input` with `{ text: synthesized, clarificationAnswer: true, intentHint: "resume_clarification" }`. Main calls `client.sendInput` with `clarification_answer=true`.
4. Daemon emits `clarification.answered` + synthesized `step_completed`; renderer marks the card resolved and resumes streaming.
5. Safety net: if the stream ends while a clarification is pending for a tab, suppress the generic "stream ended" error card (mirrors TUI behavior).

## IPC contract

All channels typed in `src/shared/ipc.ts`; preload exposes a single `window.soothe` object via `contextBridge.exposeInMainWorld`.

| Channel | Direction | Payload |
| --- | --- | --- |
| `daemon:health` | renderer→main, request/response | `{}` → `{live, version?, error?}` |
| `loops:list` | renderer→main, request/response | `{}` → daemon `loop_list_response` |
| `tab:open` | renderer→main, request/response | `{loopId?}` → `{tabId, loopId}` |
| `tab:input` | renderer→main, fire | `{tabId, text, attachments?, clarificationAnswer?, intentHint?, modelOverride?}` |
| `tab:command` | renderer→main, fire | `{tabId, cmd}` |
| `tab:close` | renderer→main, fire | `{tabId, mode: "detach"\|"delete"}` |
| `tab:event` | main→renderer, push | `{tabId, event}` (decoded daemon event) |
| `tab:status` | main→renderer, push | `{tabId, state: "connecting"\|"ready"\|"reconnecting"\|"error", error?}` |
| `settings:get` / `settings:set` | both | daemon URL, theme |

## Module layout (new files under `apps/soothe-desktop/`)

The submodule currently contains only `LICENSE`. Create the following:

```
apps/soothe-desktop/
├── package.json                     # private; declares electron, vite, react, tailwind,
│                                    # shadcn deps; "soothe-client-typescript": "file:../../client/typescript"
├── electron.vite.config.ts          # main/preload/renderer build config
├── electron-builder.yml             # Mac DMG first; Windows/Linux configs stubbed
├── tailwind.config.js · postcss.config.js · tsconfig.json · tsconfig.node.json
├── README.md                        # dev quickstart only
├── src/
│   ├── shared/
│   │   ├── ipc.ts                   # channel names + request/response types
│   │   └── events.ts                # re-exports from soothe-client-typescript
│   ├── main/
│   │   ├── index.ts                 # app entry (createWindow, app.whenReady)
│   │   ├── windowing.ts
│   │   ├── daemon/
│   │   │   ├── manager.ts           # WSManager — Map<tabId, Client>; reconnect logic
│   │   │   ├── health.ts            # checkDaemonStatus probe + polling
│   │   │   └── settings.ts          # electron-store wrapper (URL, theme)
│   │   └── ipc/
│   │       ├── channels.ts          # ipcMain.handle wiring
│   │       └── handlers/{tab,loops,daemon,settings}.ts
│   ├── preload/index.ts             # contextBridge.exposeInMainWorld('soothe', api)
│   └── renderer/
│       ├── index.html
│       ├── main.tsx
│       ├── app/{App,Sidebar,TabBar,TabView,EmptyState}.tsx
│       ├── features/
│       │   ├── chat/ChatScroll.tsx · MessageList.tsx
│       │   ├── composer/Composer.tsx · AttachmentStrip.tsx
│       │   ├── clarification/ClarificationCard.tsx
│       │   ├── loops/LoopsSidebar.tsx
│       │   ├── settings/SettingsDialog.tsx
│       │   └── command-palette/CommandPalette.tsx
│       ├── event-renderers/
│       │   ├── registry.ts          # type → component map
│       │   ├── reasoning.tsx · tool.tsx · diff.tsx · subagent.tsx
│       │   ├── final-report.tsx · error.tsx · fallback.tsx
│       ├── state/
│       │   ├── store.ts             # zustand root
│       │   └── slices/{tabs,loops,events,settings,clarification}.ts
│       ├── lib/{ipc.ts,markdown.tsx,diff.tsx,format.ts}
│       └── ui/                      # shadcn primitives generated via CLI
└── tests/                           # vitest for state slices + renderers; playwright later
```

## Reused / referenced existing code

- **TypeScript client**: `client/typescript/src/{client.ts,protocol.ts,events.ts,session.ts,helpers.ts}` — used as-is from main process via `file:` dependency.
- **Event taxonomy**: `packages/soothe-sdk/src/soothe_sdk/core/events.py` and TS mirror in `client/typescript/src/events.ts` define the `soothe.*` event types the renderer registry keys off.
- **Clarification semantics**: mirrors `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py:3549` (TUI `ClarificationInputMessage`) and the resume flow in `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` (around line 1594).
- **Image attachment shape**: matches `tui/textual_adapter.py:1609-1623` payload (`attachments[]` on `loop_input`).
- **Slash command set**: pull MVP subset from `packages/soothe-cli/src/soothe_cli/tui/command_registry.py:58`; skills from `skills_list` RPC.
- **Daemon CORS**: ensure renderer Origin matches default allowlist in `packages/soothe-daemon/src/soothe_daemon/config/models.py:35` (or document a `transport.websocket.cors_origins` addition for `app://` if needed).

## Tech choices (locked for MVP)

| Concern | Choice |
| --- | --- |
| Shell | Electron (latest LTS) |
| Build | electron-vite (HMR for renderer + main reload) |
| UI | React 18 + TypeScript |
| Styling / components | Tailwind CSS + shadcn/ui (Radix primitives) |
| State | zustand (one root store, sliced) |
| Virtualization | react-virtuoso (chat scroll) |
| Markdown | react-markdown + remark-gfm + shiki |
| Diff | react-diff-view (lightweight) |
| Settings storage | electron-store |
| Packaging | electron-builder (DMG first; NSIS/AppImage stubs) |
| Tests | vitest (unit), playwright-electron (E2E, post-MVP) |
| Logging | electron-log |
| Package manager | pnpm (standalone, not workspace, until a second TS package exists) |

## Verification

Manual end-to-end smoke checklist (all must pass before merging the MVP):

1. **Daemon not running** → app launches, shows empty state with `soothed start` command; Retry succeeds once daemon is up.
2. **New chat** → click "New chat", composer enabled, type prompt + send → reasoning card streams, final assistant markdown renders, tool cards expand/collapse.
3. **Sidebar reattach** → close app, restart daemon-managed loops, reopen app → sidebar lists loops; click one → history replays into scroll, live updates resume.
4. **Multi-tab concurrency** → open 2 tabs, send prompts in both, confirm each tab streams its own loop without cross-talk; switch tabs without losing background activity.
5. **Clarification flow** → run a prompt that triggers `ask_user` (manual mode via Shift+Tab) → inline card appears in chat with amber tab badge; submit answers → loop resumes; card resolves.
6. **File diff card** → trigger an edit-file tool call → diff card renders with expandable hunks.
7. **Image attachment** → paste/drag-drop an image into composer → thumbnail appears → send → daemon receives image and the next assistant turn references it.
8. **Slash palette** → type `/` → palette opens with `/clear`, `/cancel`, `/exit`, `/quit` + any `/skill:*` from `skills_list`; pick `/clear` → chat clears.
9. **Settings round-trip** → change daemon URL to an invalid port → app shows reconnecting, then error; restore → recovers.

Automated (must pass `pnpm test` before merge):

- vitest covering: IPC channel encode/decode, event-renderer registry resolution, clarification state machine, zustand tab slice (open/close/detach), composer keymap.

## Hand-off

Approved → Platonic Coding Phase 1 (RFC formalization): generate an RFC from this design covering desktop-client architecture and `soothe-client-typescript` integration points, then run `specs-refine`. Implementation work after RFC approval should land in `apps/soothe-desktop/` (submodule) with a tracking IG under `docs/impl/`.
