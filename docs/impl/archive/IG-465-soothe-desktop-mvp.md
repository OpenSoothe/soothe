# IG-465: Soothe Desktop MVP

## Goal

Implement the soothe-desktop MVP per RFC-505: an Electron + React desktop client under `apps/soothe-desktop` (git submodule) that connects to a user-managed `soothed` via the existing `soothe-client-typescript` package.

Scope is fixed by RFC-505 §2: tab-per-loop chat with streaming reasoning/tool cards, inline clarification widget, slash command palette + skill invocation, file-change diff cards, image attachments, sidebar loop history, settings. Out of scope (deferred): model picker, MCP viewer, autopilot dashboard, loop-tree visualization, multi-window, auto-update, authentication.

Source RFCs: [RFC-505](../specs/RFC-505-soothe-desktop-client.md) (primary), RFC-403, RFC-450, RFC-454, RFC-500, RFC-503, RFC-504.

## Milestone breakdown

The build splits into five milestones, each independently runnable. Each milestone has a `pnpm dev` smoke check.

| ID | Milestone | Headline deliverable |
|----|-----------|----------------------|
| M1 | Scaffold + IPC bridge | App boots, "Hello" renderer, typed IPC roundtrip, daemon health probe surfaced |
| M2 | Tab lifecycle + chat streaming | Open new chat, send text, see streaming text + reasoning/tool cards; reattach existing loops with history replay |
| M3 | Clarification + composer features | Inline ClarificationCard with resume; slash palette w/ static commands + dynamic skills; Esc=interrupt, Cmd/Ctrl+K palette |
| M4 | Diffs + attachments | DiffCard for file-edit frames; image paste/drag-drop into composer; attachments forwarded |
| M5 | Settings + packaging | Settings dialog (daemon URL, theme); electron-builder DMG; README quickstart |

## M1 — Scaffold + IPC bridge

**Files created (all in `apps/soothe-desktop/`):**

```
package.json                     # private; pnpm
electron.vite.config.ts
tsconfig.json · tsconfig.node.json
tailwind.config.js · postcss.config.js
.gitignore · .npmrc
README.md
src/
├── shared/ipc.ts                # channel constants + payload types
├── main/
│   ├── index.ts                 # app.whenReady → BrowserWindow + ipcMain.handle bindings
│   ├── windowing.ts
│   ├── daemon/health.ts         # wraps checkDaemonStatus from soothe-client-typescript
│   ├── daemon/settings.ts       # electron-store wrapper
│   └── ipc/handlers/daemon.ts   # daemon:health, settings:get/set
├── preload/index.ts             # contextBridge.exposeInMainWorld('soothe', api)
└── renderer/
    ├── index.html
    ├── main.tsx                 # React root mount
    ├── app/App.tsx              # AppShell skeleton (sidebar | tab bar | main)
    ├── app/EmptyState.tsx       # shown when daemon unreachable
    ├── lib/ipc.ts               # typed window.soothe accessor
    └── ui/                      # initial shadcn primitives (button, dialog, input)
```

**Key decisions for M1:**
- `package.json` declares `"soothe-client-typescript": "file:../../client/typescript"` and `"private": true`.
- Electron security: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true` for renderer.
- `electron-vite` config with three entry points; HMR for renderer.
- Pre-bundled shadcn/ui via the CLI; install Tailwind v3 (Tailwind v4 alpha not pinned).

**Smoke check (M1):**
1. `pnpm install && pnpm dev` opens a window.
2. With `soothed` not running, EmptyState renders the "daemon not reachable" message plus `soothed start` snippet.
3. Start `soothed`, click Retry → health banner clears, sidebar area shows "No loops yet."

## M2 — Tab lifecycle + chat streaming

**Files created:**

```
src/main/daemon/manager.ts       # WSManager: Map<tabId, Client>
src/main/ipc/handlers/tab.ts     # tab:open, tab:input, tab:close
src/main/ipc/handlers/loops.ts   # loops:list, loops:delete
src/renderer/state/store.ts      # zustand root
src/renderer/state/slices/tabs.ts
src/renderer/state/slices/loops.ts
src/renderer/state/slices/events.ts
src/renderer/app/Sidebar.tsx     # LoopsSidebar
src/renderer/app/TabBar.tsx
src/renderer/app/TabView.tsx
src/renderer/features/chat/ChatScroll.tsx   # react-virtuoso
src/renderer/features/chat/MessageList.tsx
src/renderer/features/composer/Composer.tsx # textarea only in M2 (palette + atts in M3/M4)
src/renderer/event-renderers/registry.ts
src/renderer/event-renderers/{assistant,reasoning,tool,subagent,final-report,error,fallback}.tsx
src/renderer/lib/markdown.tsx    # react-markdown + remark-gfm + shiki
```

**WSManager behavior** (`src/main/daemon/manager.ts`):
- `open(opts: {loopId?: string}) → Promise<{tabId, loopId}>`:
  1. `new Client(daemonUrl)`, `client.connect()`, `client.waitForDaemonReady()`.
  2. If `opts.loopId` undefined: `client.sendLoopNew()`, await `loop_new_response`, extract `loop_id`.
  3. If `opts.loopId`: prefer `client.sendLoopReattach(loopId)`; renderer consumes history_replay frames.
  4. `client.sendLoopSubscribe(loopId, "full", "adaptive")`; `client.waitForSubscriptionConfirmed(loopId, ...)`.
  5. Generate `tabId` (`crypto.randomUUID()`), store `{tabId, loopId, client}` in map.
  6. Start consume loop: `for await (const msg of client.receiveMessages())` → `webContents.send('tab:event', {tabId, event: msg})`.
- `close(tabId, mode)`:
  - `detach`: `client.sendLoopDetach(loopId); client.close()`.
  - `delete`: `client.deleteLoop(loopId); client.close()`.
- `input(tabId, payload)`: `client.sendInput(payload.text, {loopID: loopId, attachments: payload.attachments, ...})`.

**Renderer event-registry resolution** (`src/renderer/event-renderers/registry.ts`):
- Exact match on `event.type` → most-specific glob match (e.g. `soothe.tool.execution.*`) → `FallbackDebugCard`.
- Each renderer accepts `{ event, tabId, append }` props.
- Streaming text coalescing: an `AssistantBubble` accumulates `AIMessageChunk` text until the next non-chunk event.

**Smoke check (M2):**
1. Click "New chat" → sidebar shows pending entry, tab opens, status "connecting" → "ready".
2. Type "hello" → daemon responds → reasoning card streams, AssistantBubble fills, FinalReport card appears.
3. Close tab → loop still listed in sidebar (detached, not deleted).
4. Click sidebar entry → reopens tab; history_replay rebuilds the prior chat.
5. Open two tabs, send prompts in both → each streams independently, no cross-talk.

## M3 — Clarification + composer features

**Files created:**

```
src/renderer/features/clarification/ClarificationCard.tsx
src/renderer/state/slices/clarification.ts
src/renderer/features/command-palette/CommandPalette.tsx  # global Cmd/Ctrl+K
src/renderer/features/composer/SlashPalette.tsx           # `/` autocomplete inside composer
src/renderer/event-renderers/clarification.tsx
src/main/ipc/handlers/skills.ts                           # skills:list (cached per tab)
```

**ClarificationCard semantics:**
- Mounts when `soothe.loop.clarification.requested` arrives for the tab.
- Renders one `Input` per question; submit consolidates answers as `"Q1: A1\nQ2: A2"` text.
- On submit: `window.soothe.tabInput({tabId, text, clarificationAnswer: true, intentHint: "resume_clarification"})`.
- `clarificationSlice` stores `Map<tabId, {questions, status: "pending"|"resolved"}>`; `TabBar` reads it to show the amber badge.
- "Stream ended" guard: while `status === "pending"`, swallow envelope `error` frames with `code === "stream_ended"`.

**Slash palette:**
- Triggered when composer text starts with `/`.
- Sources: static `["/clear", "/cancel", "/exit", "/quit"]` ∪ `skills:list` cache → mapped to `/skill:<name>`.
- Selection: rewrites composer to picked command; for `skill:` prefixes the user can append args.
- Send: rewrites to `tab:command` (`/clear`, `/cancel`, etc.) or `tab:input` with `intentHint` for skills (see `tui/skills/invocation.py` for parity).

**Skills handler** (`src/main/ipc/handlers/skills.ts`):
- Caches `Client.listSkills()` per-tab on first request; renderer calls `window.soothe.skillsList({tabId})`.

**Keymap (Composer):**
- `Enter` → send · `Shift+Enter` → newline · `Esc` → `tab:command "/cancel"` · `Cmd/Ctrl+K` → global palette · `Shift+Tab` → toggle `clarificationMode` (UI-only badge today; daemon mode toggle deferred).

**Smoke check (M3):**
1. Trigger a prompt that invokes `ask_user` → ClarificationCard appears inline, tab badge amber.
2. Fill answers, submit → card resolves, agent continues.
3. Type `/cle` → palette shows `/clear`; pick it → chat cleared.
4. Type `/skill:` → palette lists daemon skills; pick one → composer rewritten.
5. Cmd/Ctrl+K opens global palette.

## M4 — Diffs + attachments

**Files created:**

```
src/renderer/event-renderers/diff.tsx        # uses react-diff-view
src/renderer/lib/diff.ts                     # unified-diff parsing helpers
src/renderer/features/composer/AttachmentStrip.tsx
src/renderer/lib/attachments.ts              # paste/drop/file-input → {filename, mimeType, base64}
```

**DiffCard event mapping:**
- Subscribe in registry to file-edit event types as they appear on the wire (mirrors `tui/widgets/file_change_preview.py`'s consumed event family).
- If wire frame carries a unified diff: render with `react-diff-view` (side-by-side fallback to inline on narrow widths).
- If frame carries before/after blobs: compute diff client-side via `diff` package.

**Attachments:**
- `Composer` listens for `paste` and `drop` events; calls `attachments.fromFiles(files)` to base64-encode.
- `AttachmentStrip` renders thumbnails above the textarea with remove buttons.
- On send: `tab:input` payload includes `attachments: [{filename, mimeType, base64}, ...]`; main forwards to `client.sendInput(text, {attachments: [...]})`.

**Smoke check (M4):**
1. Run a prompt that triggers a file edit → DiffCard renders with collapsible hunks.
2. Paste an image into the composer → thumbnail appears.
3. Drag a PNG onto the window → same result.
4. Send → next assistant turn references the image.

## M5 — Settings + packaging

**Files created:**

```
src/renderer/features/settings/SettingsDialog.tsx
electron-builder.yml
build/icons/icon.icns (placeholder)
README.md updated with `pnpm dev` / `pnpm package` quickstart
```

**SettingsDialog fields:**
- Daemon URL (validated as `ws://` or `wss://`)
- Theme (`light` | `dark` | `system`)
- Bound to `settings:set` channel; live-updates new tab connections (existing tabs persist their connection until reopened).

**electron-builder.yml:**
- `appId: dev.mirasurf.soothe-desktop`
- Targets: `mac` (`dmg`, arm64+x64), `win` and `linux` configured but unused in M5.
- `files: ["dist/**", "package.json"]`; ASAR enabled.

**Smoke check (M5):**
1. Open Settings → change daemon URL → reconnect.
2. `pnpm package` produces a `.dmg` in `release/`.
3. Open the DMG → drag to Applications → launch → app starts, finds daemon.

## Dependencies

`package.json` runtime deps:
- `electron` (latest LTS)
- `react`, `react-dom`
- `zustand`
- `react-virtuoso`
- `react-markdown`, `remark-gfm`, `shiki`
- `react-diff-view`, `diff`
- `electron-store`
- `cmdk` (shadcn/ui transitive)
- `soothe-client-typescript` via `file:../../client/typescript`

dev deps:
- `electron-vite`, `vite`, `typescript`
- `tailwindcss`, `postcss`, `autoprefixer`
- `@vitejs/plugin-react`
- `electron-builder`
- `vitest`, `@testing-library/react`, `jsdom`
- `eslint`, `prettier`

## Testing

Per CLAUDE.md "tests in package directories", desktop tests live in `apps/soothe-desktop/tests/`:

```
tests/
├── unit/
│   ├── state/         # zustand slices (tabs, loops, events, clarification)
│   ├── event-renderers/registry.test.tsx
│   ├── lib/diff.test.ts · attachments.test.ts
│   └── shared/ipc.test.ts          # payload type roundtrip
└── e2e/               # placeholder for playwright-electron, post-MVP
```

`pnpm test` runs vitest. No daemon needed for unit tests (IPC and Client are mocked).

## Verification

After each milestone, run the milestone smoke check. After M5, the full RFC-505 §11 manual checklist (9 items) must pass before merging the submodule.

## Open questions deferred to implementation

From RFC-505 §10:
1. **CORS Origin** — empirically verify which Origin the Electron main process sends; if it falls outside the daemon's default `cors_origins`, document the required allowlist addition in M5 README.
2. **Renderer HMR vs WSManager** — ensure renderer reloads do not orphan main-side `Client` instances. Implement teardown on `webContents.on('did-finish-load')` if the renderer drops without `tab:close`.
3. **AIMessageChunk coalescing** — implement in renderer (M2) as the simpler option; profile if it causes re-render storms.

## Files touched in the main repo

Outside `apps/soothe-desktop/` (the submodule), expected main-repo changes during implementation are limited to:
- This guide (`docs/impl/IG-465-soothe-desktop-mvp.md`).
- Submodule pointer bump in `.gitmodules` / main repo once the desktop repo gains commits (handled by `git submodule update`).
- Possible follow-up RFC if `transport.websocket.cors_origins` needs a new default (would amend RFC-450, not RFC-505).
