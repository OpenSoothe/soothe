# Soothe Desktop App Product Redesign

> **Status**: Draft - Pending Review
> **Date**: 2026-06-04
> **RFC Assignment**: RFC-700 series (Desktop App)
> **Scope**: `apps/soothe-desktop` (Electron + React + Tailwind + Zustand)
> **Cross-package impacts**: Noted as future integration points

---

## Executive Summary

This redesign transforms the Soothe Desktop app from a single-purpose chat interface into a **project-centric workspace** supporting two resource types: **Chats** (ordinary loops) and **Autopilot Jobs** (multi-loop autonomous sessions). The design introduces:

- Project as the working unit (workspace = project)
- Side panel navigation with chats and jobs lists
- Autopilot job creation dialog
- DAG visualization for job goal tracking
- Loop Observation Room (LOR) for monitoring autopilot loops

---

## 1. Project + Resources Foundation

### 1.1 Project Identity

| Aspect | Design |
|--------|--------|
| Identity | Workspace directory path = one project |
| Config files | `.soothe/project.yml` (static app-level settings) |
| Agent config | `.soothe/config/config.yml` (future work - project-specific agent config not implemented in this phase) |
| Runtime data | `.soothe/resources.db` (SQLite for chats/jobs registry) |

### 1.2 Global Desktop Preferences

| File | Location | Contents |
|------|----------|----------|
| `desktop_prefs.yml` | `~/.soothe/config/` | `last_project_path`, `theme`, `window_size` |

- Stored outside any specific project (global across all workspaces)
- Auto-loads last active project on app launch
- If path invalid, shows project picker dialog

### 1.3 Resource Types

| Type | Definition | Daemon Entity | UI View |
|------|------------|---------------|---------|
| **Chat** | Ordinary loop, single conversation thread | Loop with checkpoint history | Message list + input composer |
| **Job** | Autopilot session, one GoalEngine invocation with root goal, spawns multiple child loops | AutopilotService instance | DAG visualization + loop observation room |

### 1.4 SQLite Schema

Location: `.soothe/resources.db` (per-project database)

```sql
-- Chats table
CREATE TABLE chats (
  id TEXT PRIMARY KEY,              -- loop_id from daemon
  name TEXT,                        -- LLM-generated, user-editable
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  is_archived BOOLEAN DEFAULT FALSE,
  message_count INTEGER DEFAULT 0   -- cached for quick display
);

-- Jobs table
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,              -- job entity ID (8-char hex)
  name TEXT,                        -- LLM-generated from root goal
  goal TEXT NOT NULL,               -- full goal description
  verification_rules TEXT,          -- optional, freeform text
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  is_archived BOOLEAN DEFAULT FALSE,
  status TEXT DEFAULT 'pending',    -- cached: pending/running/paused/completed/failed
  active_goals_count INTEGER DEFAULT 0,
  completed_goals_count INTEGER DEFAULT 0,
  total_goals_count INTEGER DEFAULT 0,
  last_error TEXT                   -- cached error info
);

-- Job-loops mapping (child loops spawned by job)
CREATE TABLE job_loops (
  job_id TEXT NOT NULL,
  loop_id TEXT NOT NULL,
  PRIMARY KEY (job_id, loop_id),
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Archive tables (soft delete)
CREATE TABLE chats_archive (...);  -- Same schema as chats
CREATE TABLE jobs_archive (...);   -- Same schema as jobs
```

### 1.5 Resource Behaviors

| Behavior | Design |
|----------|--------|
| Naming | LLM-generated from first prompt/goal, async background generation. Placeholder shown until name ready. |
| Deletion | Soft delete with archive tables. Recoverable. Loop checkpoint history preserved in daemon. |
| Multi-project | Single project per window. Multiple windows for different projects. |
| Project loading | Auto-load last active project from `desktop_prefs.yml`. Show picker if path invalid. |
| First-time setup | Prompt dialog: "Initialize Soothe project in this workspace?" Creates `.soothe/` structure if confirmed. |
| Status authority | Desktop caches small fields for quick display. Daemon queried for authoritative execution state. |

---

## 2. Navigation & Side Panel UI

### 2.1 Side Panel Layout

| Aspect | Design |
|--------|--------|
| Position | Left sidebar |
| Structure | Collapsible tree-style panel |
| Sections | "Chats" and "Jobs" - expandable/collapsible headers |
| Width | Resizable via drag edge, toggle hide via keyboard shortcut |

### 2.2 Side Panel Header

| Element | Design |
|---------|--------|
| Project selector | Project name (click opens native folder picker) |
| Actions | "New Chat" button, "New Job" button |
| Location | Top of side panel |

### 2.3 Section Headers

| Format | Example |
|--------|---------|
| Expand/collapse arrow + count badge | "Chats ▼ (5)" / "Jobs ▲ (3)" |

### 2.4 Resource Item Display

| Type | Format | Example |
|------|--------|---------|
| Chat | Name + status dot + timestamp | "Fix login bug ● 2h ago" |
| Job | Name + status dot + duration | "Refactor API ● 45m" |

### 2.5 Item Interaction

| Action | Behavior |
|--------|----------|
| Left-click | Opens resource in main panel (new tab or switches active tab) |
| Right-click | Context menu: Rename, Archive, Delete, Copy ID |

### 2.6 Keyboard Navigation

| Key | Action |
|-----|--------|
| Arrow Up/Down | Navigate items within active section |
| Enter | Open selected item |
| Escape | Close/hide side panel |

### 2.7 Status Colors

| Status | Color | Applies To |
|--------|-------|------------|
| Active | Green | Chats, Jobs |
| Idle | Grey | Chats, Jobs |
| Error | Red | Chats, Jobs |
| Waiting/Paused | Yellow | Jobs |

---

## 3. Autopilot Job Creation Dialog

### 3.1 Dialog Trigger

| Entry Point | "New Job" button in side panel header |

### 3.2 Dialog Structure

| Field | Required | Format | Description |
|-------|----------|--------|-------------|
| Goal | Yes | Large textarea (multi-line) | Full description of what autopilot should accomplish |
| Verification rules | No | Freeform textarea (expandable section) | Optional criteria for validating goal completion |

**Placeholder text for Goal**: "Describe what the autopilot should accomplish in detail..."

### 3.3 Dialog Actions

| Button | Behavior |
|--------|----------|
| Create | Creates job AND starts autopilot execution immediately |
| Cancel | Closes dialog, no job created |

### 3.4 Post-Creation Behavior

- Job appears in side panel with "running" status
- Main panel opens job view showing DAG visualization
- Duration timer starts

### 3.5 Editing Existing Jobs

| Aspect | Design |
|--------|--------|
| Editability | Only when paused or stopped |
| Trigger | Right-click menu: "Edit Config" on paused jobs |
| Dialog | Same fields as creation |
| Buttons | "Save Changes" + "Cancel" |
| Title | "Edit Job" |

---

## 4. Job DAG Visualization (Main Panel)

### 4.1 Technology

| Library | React Flow |
| Purpose | DAG rendering, hierarchical layout, custom nodes |
| Layout engine | dagre (via @reactflow/dagre or similar) |
| Integration | Fits existing React + Tailwind stack |

### 4.2 DAG Layout

| Aspect | Design |
|--------|--------|
| Orientation | Top-down hierarchical tree |
| Root position | Top of graph |
| Connections | Lines/arrows showing dependency edges (`depends_on`) |
| Interactions | Zoom, pan, node selection, minimap optional |

### 4.3 Node Component: GoalNode

**Visual structure:**

```
┌─────────────────────────────────┐
│ Goal Title (truncated)          │ ← Status-colored border
│ ● Active                        │ ← Status badge
│ [████████░░░░░░░░] 8/12 steps  │ ← Progress bar
│ 🛠 5                           │ ← Tool count badge
└─────────────────────────────────┘
```

**Elements:**

| Element | Design |
|---------|--------|
| Title | Goal short description, truncated if long |
| Status badge | Icon + text (● Active, ✓ Completed, ⏸ Paused, etc.) |
| Border | Colored border matching status |
| Progress bar | Visual bar showing steps completion |
| Tool count | Badge showing number of tool calls |
| Hover tooltip | Goal description excerpt, completion status, key findings preview |

### 4.4 Node Status Colors

| Status | Badge | Border Color |
|--------|-------|--------------|
| Pending | ● Pending | Grey |
| Active | ● Active | Green |
| Completed | ✓ Completed | Blue |
| Failed | ✗ Failed | Red |
| Blocked | ⏸ Blocked | Yellow |
| Awaiting clarification | ❓ Clarifying | Orange |

### 4.5 Loop Navigation from DAG

| Aspect | Design |
|--------|--------|
| Trigger | Click on DAG node |
| Behavior | Opens goal's assigned loop in new tab |
| DAG view | Preserved in original tab (user can switch between) |

### 4.6 Loop View: Lineage Panel

When viewing a loop opened from DAG node:

| Element | Design |
|---------|--------|
| Header breadcrumb | "Goal: Fix login bug" + parent goal name if any |
| Side panel | Sibling goals list (other children of same parent goal) |

### 4.7 Main Panel Layout for Job View

| Element | Design |
|---------|--------|
| Primary content | DAG visualization fills main panel |
| Toolbar (top) | Job name, status indicator, controls |
| Controls | Pause/Resume button, Cancel button |

---

## 5. Loop Observation Room (LOR)

### 5.1 Concept

The Loop Observation Room (LOR) is a special view for loops running under autopilot control. It provides:

- **Readonly message list**: Watch agent work without interrupting
- **Comment panel**: Add guidance/instructions to influence agent behavior

### 5.2 Layout Structure

| Aspect | Design |
|--------|--------|
| Split | 70% message list (left), 30% comment panel (right) |
| Mode trigger | `isObservationMode: true` flag passed when opening from DAG node |

### 5.3 Message List (Readonly)

| Aspect | Design |
|--------|--------|
| Interactions | Scroll, hover for details, click to expand tool/reasoning cards |
| Content types | All existing event types: plan, reasoning, steps, tool execution, goal reports, subagent events, etc. |
| Input | No input composer - pure observation mode |

### 5.4 Comment Attachment

| Aspect | Design |
|--------|--------|
| Trigger | Hover on AI message or step card reveals "Add comment" button (💬 icon) |
| Selection | Clicking button focuses comment panel input on that card |
| Visual marker | Comment badge appears on cards that have comments attached |

### 5.5 Comment Panel

| Aspect | Design |
|--------|--------|
| Layout | Grouped by target card |
| Group structure | Card excerpt/reference → list of comments below |
| Input | Textarea appears when card selected for commenting |
| History | All comments visible with timestamp + "sent" status (✓ checkmark) |

### 5.6 Comment Absorption

| Aspect | Design |
|--------|--------|
| Mechanism | Sent as guidance events to daemon via WebSocket/IPC |
| Target | Autopilot/GoalEngine receives and adjusts behavior asynchronously |
| Feedback | Comment shows "sent" status after submission (checkmark indicator) |

### 5.7 Visual Markers on Cards

| Marker | Design |
|--------|--------|
| Icon | 💬 comment bubble badge in card corner |
| Multiple comments | Badge shows count (💬 3) |
| Badge action | Click badge scrolls comment panel to that card's comment group |

### 5.8 Mode Determination: LOR vs Regular Chat

| Context | Mode |
|---------|------|
| Opened from DAG node | LOR (isObservationMode: true) |
| Opened from side panel "Chats" section | Regular chat (interactive composer) |

---

## 6. Cross-Package Integration Points

> **Note**: The following require changes outside `apps/soothe-desktop`. Implementation deferred pending approval.

### 6.1 Guidance Event Type

| Change | Package | Description |
|--------|---------|-------------|
| New event type: `soothe.loop.guidance` | soothe-daemon / soothe | Event for absorbing user comments from LOR into GoalEngine |

### 6.2 Autopilot Job Entity

| Change | Package | Description |
|--------|---------|-------------|
| Job ID generation and tracking | soothe (core/autopilot) | Create job entity with unique ID, track spawned loops |
| Job-loops mapping | soothe-daemon | Persist relationship between job and its child loops |
| Job lifecycle: pending → running → paused → completed → failed | soothe (core/autopilot) | State machine for job status |

### 6.3 IPC/WebSocket Commands

| Command | Package | Description |
|---------|---------|-------------|
| `job_create` | soothe-daemon | Create new autopilot job with goal + verification rules |
| `job_status` | soothe-daemon | Query job status, goal counts, DAG state |
| `job_pause` / `job_resume` | soothe-daemon | Control job execution |
| `job_cancel` | soothe-daemon | Cancel running job |
| `job_dag` | soothe-daemon | Get full DAG data for visualization |
| `loop_guidance` | soothe-daemon | Send guidance comment to specific loop |

### 6.4 GoalEngine Integration

| Integration | Description |
|-------------|-------------|
| Guidance absorption | GoalEngine receives guidance events and adjusts goal priorities, constraints, or subgoal creation |
| DAG state export | GoalEngine exposes DAG structure for desktop visualization |
| Goal progress reporting | GoalEngine reports step completion, tool counts for node display |

---

## 7. Implementation Phases

### Phase 1: Foundation (Weeks 1-2)

- Project identity and SQLite schema
- Global preferences persistence
- Side panel structure and sections
- Resource item display and interactions

### Phase 2: Job Management (Weeks 3-4)

- Job creation dialog
- Job editing dialog
- Job lifecycle in SQLite
- Side panel job section interactions

### Phase 3: DAG Visualization (Weeks 5-6)

- React Flow integration
- Custom GoalNode component
- DAG data fetching from daemon
- Loop navigation from node click

### Phase 4: Loop Observation Room (Weeks 7-8)

- LOR layout implementation
- Comment attachment UI
- Comment panel with grouping
- Guidance event sending

### Phase 5: Polish & Integration (Week 9-10)

- Keyboard shortcuts refinement
- Status sync optimization
- Error handling and edge cases
- Cross-package integration testing

---

## 8. Open Questions

| Question | Status |
|----------|--------|
| Should job DAG support manual goal reordering? | Deferred - autopilot manages DAG |
| Should comments support rich formatting (markdown)? | Deferred - start with plain text |
| Should LOR support multiple observers (multi-user)? | Deferred - single-user scope |
| Should job config support resource limits (max loops, timeout)? | Future consideration |

---

## Appendix A: Existing Architecture Reference

### A.1 Current Desktop App Stack

| Component | Technology |
|-----------|------------|
| Framework | Electron v33 |
| UI | React 18 |
| Styling | Tailwind CSS + CSS variables |
| State | Zustand with subscribeWithSelector |
| Virtualization | react-virtuoso |
| Command palette | cmdk |
| Markdown | react-markdown + remark-gfm |
| Daemon connection | @mirasoth/soothe-client (WebSocket) |

### A.2 IPC Bridge Pattern

```typescript
// preload/index.ts
contextBridge.exposeInMainWorld('soothe', {
  tabOpen: (loopId) => ipcRenderer.invoke('tab-open', loopId),
  tabInput: (tabId, message) => ipcRenderer.invoke('tab-input', tabId, message),
  onTabEvent: (callback) => ipcRenderer.on('tab-event', callback),
  // ... existing channels
});
```

### A.3 Event Renderer Registry

```typescript
// event-renderers/registry.tsx
registerRenderer('soothe.tool.execution.*', ToolCard);
registerRenderer('soothe.loop.clarification.*', ClarificationCard);
registerRenderer('AIMessageChunk', AssistantBubble);
```

---

## Appendix B: UI Component Inventory

### B.1 Existing Components (Reuse)

| Component | Location | Reuse In |
|-----------|----------|----------|
| Button | `renderer/ui/button.tsx` | Dialog buttons, toolbar |
| Dialog | `renderer/ui/dialog.tsx` | Job creation/edit dialogs |
| Input | `renderer/ui/input.tsx` | Form fields |
| Card | `renderer/ui/card.tsx` | GoalNode styling reference |
| MessageList | `renderer/features/chat/MessageList.tsx` | LOR message list (readonly variant) |
| Composer | `renderer/features/composer/Composer.tsx` | Regular chat only (not LOR) |

### B.2 New Components Required

| Component | Purpose |
|-----------|---------|
| ProjectSelector | Header project name + folder picker trigger |
| SidePanel | Collapsible tree sidebar container |
| ChatSection | Expandable chats list section |
| JobSection | Expandable jobs list section |
| ChatItem | Single chat row in list |
| JobItem | Single job row in list |
| JobCreateDialog | Modal for creating/editing jobs |
| JobView | Main panel container for DAG |
| JobToolbar | Top bar with controls |
| GoalDAG | React Flow DAG component |
| GoalNode | Custom React Flow node card |
| GoalTooltip | Hover tooltip for node details |
| LineagePanel | Side panel showing goal siblings |
| LORLayout | Split view container |
| LORMessageList | Readonly message list variant |
| CommentPanel | Right panel for comments |
| CommentGroup | Comments attached to one card |
| CommentBadge | Icon badge on cards with comments |

---

*End of Design Draft*