# RFC-700: Desktop App Product Redesign

**RFC**: 700
**Title**: Desktop App Product Redesign
**Status**: Proposed
**Kind**: Product Specification
**Created**: 2026-06-04
**Updated**: 2026-06-04
**Dependencies**: RFC-222 (Autopilot and Goal Engine Architecture), RFC-228 (Autopilot Job IPC Commands), RFC-450 (Daemon Communication Protocol), RFC-200 (Autonomous Goal Management)

## Abstract

This document specifies the product redesign for the Soothe Desktop application (`apps/soothe-desktop`). The redesign transforms the app from a single-purpose chat interface into a project-centric workspace supporting two resource types: **Chats** (ordinary conversation loops) and **Autopilot Jobs** (multi-loop autonomous sessions). Key features include: project-as-unit identity, side panel navigation with resource lists, autopilot job creation dialog, DAG visualization for goal tracking, and Loop Observation Room (LOR) for monitoring autopilot loops with guidance comments.

## Overview

### Problem Statement

The current Soothe Desktop app (`apps/soothe-desktop`) provides:
- Multi-tab chat interface for conversation loops
- Sidebar showing loop list from daemon
- Message composer with slash commands
- Command palette for navigation

**Limitations**:
1. No project/workspace concept - workspace is implicit per loop
2. No distinction between ordinary chats and autopilot sessions
3. Autopilot monitoring is CLI-only (`soothe autopilot status`) - no GUI
4. No way to observe running autopilot loops or provide guidance
5. No structured job creation workflow

### Solution

Introduce **Project** as the working unit. Each project contains:
- **Chats**: Ordinary conversation loops (existing functionality)
- **Jobs**: Autopilot sessions managing goal DAGs across multiple loops

Add GUI for:
- Project selection and initialization
- Job creation with goal + verification rules
- DAG visualization showing goal progress
- Loop Observation Room (LOR) for monitoring + guidance

### Scope

| In Scope | Out of Scope (Future) |
|----------|----------------------|
| Desktop app UI redesign | Project-specific agent config |
| Project identity model | Multi-user collaboration |
| SQLite resource registry | Mobile/web client |
| Job creation dialog | Manual DAG editing |
| DAG visualization (React Flow) | Rich comment formatting |
| Loop Observation Room | Resource limits per job |

## Specification

### 1. Project Model

#### 1.1 Project Identity

A **Project** is defined as a workspace directory:

```
Project = Workspace Path
```

| Attribute | Value |
|-----------|-------|
| Identity | Directory path (e.g., `/Users/name/projects/my-app`) |
| Uniqueness | One project per directory |
| Config location | `.soothe/project.yml` (static app settings) |
| Runtime data | `.soothe/resources.db` (SQLite) |

#### 1.2 Project Directory Structure

```
<workspace>/
├── .soothe/
│   ├── project.yml          # Static project settings (app-level)
│   ├── config/
│   │   └── config.yml       # Agent config (future work)
│   └── resources.db         # SQLite: chats + jobs registry
└── ... (workspace contents)
```

#### 1.3 Global Preferences

| File | Location | Contents |
|------|----------|----------|
| `desktop_prefs.yml` | `~/.soothe/config/` | `last_project_path`, `theme`, `window_size` |

- Persists across all projects
- Auto-load last project on app launch
- Folder picker if path invalid

#### 1.4 First-Time Project Setup

When user selects a directory without `.soothe/`:

1. Show dialog: "Initialize Soothe project in this workspace?"
2. Options: Initialize / Cancel
3. On confirm: create `.soothe/`, `project.yml`, `resources.db`
4. On cancel: return to folder picker

### 2. Resource Types

#### 2.1 Chat

| Attribute | Description |
|-----------|-------------|
| Definition | Ordinary conversation loop |
| Daemon entity | Loop with LangGraph checkpoint history |
| UI view | Message list + input composer |
| Creation | "New Chat" button → creates loop in daemon |

#### 2.2 Autopilot Job

> **Note**: AutopilotService is a daemon-owned singleton (RFC-222 §86-89). A "Job" in this RFC represents a **root Goal** submitted to the singleton AutopilotService, not a separate AutopilotService instance.

| Attribute | Description |
|-----------|-------------|
| Definition | Root Goal submitted to daemon's AutopilotService |
| Daemon entity | Goal with status managed by GoalEngine (RFC-200, RFC-222) |
| Spawns | Child Goals (subgoals) assigned to StrangeLoop workers by WorkerPool |
| UI view | DAG visualization + loop observation |
| Creation | Job creation dialog → submits goal to AutopilotService |

**Goal-to-Worker Assignment**: Workers (StrangeLoop subprocesses) are fungible and assigned by WorkerPool (RFC-222 §95-104). A goal's `assigned_loop_id` references the worker currently executing it. Child goals may reuse parent's worker (lineage-aware assignment) or spawn new workers.

### 3. SQLite Schema

Location: `.soothe/resources.db`

```sql
CREATE TABLE chats (
  id TEXT PRIMARY KEY,              -- loop_id from daemon
  name TEXT,                        -- LLM-generated, user-editable
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  is_archived BOOLEAN DEFAULT FALSE,
  message_count INTEGER DEFAULT 0   -- cached for display
);

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

CREATE TABLE job_loops (
  job_id TEXT NOT NULL,
  loop_id TEXT NOT NULL,
  PRIMARY KEY (job_id, loop_id),
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Archive tables (soft delete)
CREATE TABLE chats_archive ( ... );  -- Mirror of chats
CREATE TABLE jobs_archive ( ... );   -- Mirror of jobs
```

### 4. Resource Behaviors

#### 4.1 Naming

- **Method**: LLM-generated from first prompt/goal
- **Timing**: Background async generation
- **Placeholder**: "New Chat..." / "New Job..." shown until name ready
- **Editability**: User can rename via right-click menu

#### 4.2 Deletion

- **Model**: Soft delete with archive
- **Archive tables**: Preserve deleted records
- **Recovery**: User can restore archived items
- **Daemon state**: Loop checkpoints preserved in daemon durability

#### 4.3 Multi-Project

- **Model**: Single project per window
- **Multiple projects**: Open multiple Electron windows
- **No project switching**: Each window bound to one workspace

#### 4.4 Status Authority

- **Desktop**: Stores cached fields for quick display
- **Daemon**: Authoritative for execution state
- **Query**: Desktop queries daemon for live status on panel refresh

### 5. Side Panel Navigation

#### 5.1 Layout

| Element | Design |
|---------|--------|
| Position | Left sidebar |
| Structure | Collapsible tree-style panel |
| Sections | "Chats" (expandable), "Jobs" (expandable) |
| Width | Resizable (drag edge), toggle hide (keyboard) |

#### 5.2 Header

| Element | Description |
|---------|-------------|
| Project selector | Project name, click opens folder picker |
| New Chat button | Creates new chat loop |
| New Job button | Opens job creation dialog |

#### 5.3 Section Headers

| Format | Example |
|--------|---------|
| Expand/collapse arrow + count badge | "Chats ▼ (5)" |

#### 5.4 Resource Item Display

| Type | Format | Example |
|------|--------|---------|
| Chat | Name + status dot + timestamp | "Fix login bug ● 2h ago" |
| Job | Name + status dot + duration | "Refactor API ● 45m" |

#### 5.5 Item Interactions

| Action | Behavior |
|--------|----------|
| Left-click | Open resource in main panel |
| Right-click | Context menu: Rename, Archive, Delete, Copy ID |

#### 5.6 Keyboard Navigation

| Key | Action |
|-----|--------|
| Arrow Up/Down | Navigate items |
| Enter | Open selected |
| Escape | Hide panel |

#### 5.7 Status Colors

| Status | Color |
|--------|-------|
| Active | Green |
| Idle | Grey |
| Error | Red |
| Waiting/Paused | Yellow |

### 6. Job Creation Dialog

#### 6.1 Trigger

| Entry point | "New Job" button in side panel header |

#### 6.2 Dialog Fields

| Field | Required | Format |
|-------|----------|--------|
| Goal | Yes | Large textarea (multi-line) |
| Verification rules | No | Freeform textarea (expandable) |

**Placeholder for Goal**: "Describe what the autopilot should accomplish in detail..."

#### 6.3 Dialog Actions

| Button | Behavior |
|--------|----------|
| Create | Creates job AND starts autopilot immediately |
| Cancel | Close dialog, no job created |

#### 6.4 Editing Existing Jobs

| Condition | Only when paused or stopped |
| Trigger | Right-click menu: "Edit Config" |
| Dialog | Same fields, buttons: "Save Changes" + "Cancel" |

### 7. DAG Visualization

#### 7.1 Technology

| Library | React Flow |
| Layout | dagre for hierarchical positioning |
| Integration | Custom nodes styled with Tailwind |

#### 7.2 DAG Layout

| Attribute | Design |
|-----------|--------|
| Orientation | Top-down hierarchical tree |
| Root | Top of graph |
| Edges | Lines/arrows for `depends_on` relationships |
| Interactions | Zoom, pan, node selection |

#### 7.3 GoalNode Component

```
┌─────────────────────────────────┐
│ Goal Title                      │ ← Status-colored border
│ ● Active                        │ ← Status badge
│ [████████░░░░░░░░] 8/12 steps  │ ← Progress bar
│ 🛠 5                           │ ← Tool count badge
└─────────────────────────────────┘
```

| Element | Content |
|---------|---------|
| Title | Goal short description |
| Status badge | Icon + text, colored by status |
| Border | Color matches status |
| Progress bar | Steps completion visualization |
| Tool count | Number of tool calls |
| Hover tooltip | Goal excerpt, completion status, key findings |

#### 7.4 Node Status Colors

| Status | Badge | Border |
|--------|-------|--------|
| Pending | ● Pending | Grey |
| Active | ● Active | Green |
| Completed | ✓ Completed | Blue |
| Failed | ✗ Failed | Red |
| Blocked | ⏸ Blocked | Yellow |
| Awaiting clarification | ❓ Clarifying | Orange |

#### 7.5 Loop Navigation

| Trigger | Click on DAG node |
| Behavior | Opens goal's loop in new tab |
| DAG view | Preserved in original tab |

#### 7.6 Loop View Lineage

| Element | Content |
|---------|---------|
| Header breadcrumb | Goal name + parent goal name |
| Side panel | Sibling goals list |

#### 7.7 Main Panel Layout

| Element | Description |
|---------|-------------|
| DAG | Fills main panel |
| Toolbar (top) | Job name, status, pause/resume, cancel |

### 8. Loop Observation Room (LOR)

#### 8.1 Concept

LOR is a special view for autopilot loops:
- **Readonly message list**: Watch agent without interruption
- **Comment panel**: Add guidance to influence behavior

#### 8.2 Layout

| Split | 70% messages (left), 30% comments (right) |
| Mode trigger | `isObservationMode: true` flag from DAG node |

#### 8.3 Message List

| Attribute | Design |
|-----------|--------|
| Interactions | Scroll, hover, expand cards |
| Content | All event types: plan, reasoning, steps, tools, goals |
| Input | No composer - readonly |

#### 8.4 Comment Attachment

| Trigger | Hover on AI message or step card → "Add comment" button |
| Marker | 💬 badge on cards with comments |
| Badge action | Click scrolls to comment group |

#### 8.5 Comment Panel

| Layout | Grouped by target card |
| Group structure | Card excerpt → comments list |
| Input | Textarea when card selected |
| History | Timestamped with "sent" status (✓) |

#### 8.6 Comment Absorption

> **Note**: GoalEngine runs inside daemon's AutopilotService (RFC-222 §75-89). Desktop sends guidance via WebSocket; daemon routes to AutopilotService → GoalEngine.

| Mechanism | Desktop sends via WebSocket `job_guidance` command |
| Daemon route | AutopilotService receives → routes to GoalEngine |
| Effect | GoalEngine absorbs as BackoffDecision directive (RFC-200 §208-425) |

#### 8.7 Mode Determination

| Context | Mode |
|---------|------|
| From DAG node | LOR (`isObservationMode: true`) |
| From side panel Chats | Regular chat (interactive) |

## Cross-Package Integration

> Daemon IPC commands defined in **RFC-228 (Autopilot Job IPC Commands)**.

### Daemon IPC Commands (RFC-228)

| Command | Purpose |
|---------|---------|
| `job_create` | Submit root goal to AutopilotService |
| `job_status` | Query GoalEngine.get_goal() + active worker state |
| `job_pause/resume` | Control goal execution via GoalEngine |
| `job_cancel` | Cancel root goal and all descendants |
| `job_dag` | Get GoalEngine DAG snapshot for visualization |
| `job_guidance` | Send user guidance to GoalEngine (absorbed as BackoffDecision) |
| `autopilot_subscribe` | Subscribe to autopilot worker events (bypasses `autopilot__*` filter) |
| `autopilot_unsubscribe` | Release autopilot worker subscription |

> **Note**: Worker loop_ids are namespaced `autopilot__w001`, `autopilot__w002` (RFC-222 §467-468) and **filtered from client `subscribe_loop` requests**. Desktop must use `autopilot_subscribe` (RFC-228) to receive worker events for LOR.

### Event Types

| Event | Purpose |
|-------|---------|
| `soothe.job.guidance` | User guidance sent to GoalEngine via AutopilotService |
| `soothe.goal.status` | Goal status transitions (pending → active → completed → failed) |
| `soothe.goal.progress` | Step completion, tool count updates for DAG node display |

> **Note**: Internal events like `soothe.internal.backoff` are filtered from client streams (RFC-222 §308-315). Desktop receives goal-level status events, not internal BackoffReasoner details.

### GoalEngine Integration

| Integration | Description |
|-------------|-------------|
| Guidance absorption | AutopilotService receives `job_guidance` → routes to GoalEngine → BackoffDecision (RFC-200 §208-425) |
| DAG export | `job_dag` returns GoalEngine DAG snapshot: goals with status, dependencies, assigned workers |
| Progress reporting | Goal status transitions emit `soothe.goal.*` events for desktop subscription |
| Worker subscription | `autopilot_subscribe` grants access to `autopilot__*` worker event streams |

## Implementation Phases

### Phase 1: Foundation

- Project identity, SQLite schema
- Global preferences
- Side panel structure
- Resource item display

### Phase 2: Job Management

- Job creation dialog
- Job editing
- Job lifecycle in SQLite

### Phase 3: DAG Visualization

- React Flow integration
- GoalNode component
- DAG data fetching
- Loop navigation

### Phase 4: Loop Observation Room

- LOR layout
- Comment attachment UI
- Comment panel
- Guidance event sending

### Phase 5: Polish

- Keyboard shortcuts
- Status sync optimization
- Error handling
- Cross-package integration

## References

- RFC-000: System Conceptual Design
- RFC-200: Autonomous Goal Management
- RFC-222: Autopilot and Goal Engine Architecture
- RFC-228: Autopilot Job IPC Commands
- RFC-450: Daemon Communication Protocol
- Design Draft: `docs/archive/drafts/2026-06-04-desktop-app-redesign.md`