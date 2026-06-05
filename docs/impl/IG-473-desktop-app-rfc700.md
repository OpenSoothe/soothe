# IG-473: Desktop App Implementation (RFC-700)

> **Status**: Completed
> **RFC**: RFC-700, RFC-228
> **Created**: 2026-06-05
> **Dependencies**: IG-471 (RFC-228 daemon IPC complete)

## Overview

Implement the Desktop app UI for RFC-700: Project-centric workspace with Chats and Jobs.

## Architecture

```
apps/soothe-desktop/
├── src/main/           # Electron main process (IPC handlers)
├── src/preload/        # Context bridge (window.soothe)
├── src/renderer/       # React frontend (components, state)
└── src/shared/         # Types shared across processes
```

## Implementation Phases

### Phase 1: TypeScript Types & SDK Client

**Goal**: Add RFC-228 types and client methods to soothe-sdk TypeScript client.

**Files to modify/create**:

| Package | File | Changes |
|---------|------|---------|
| soothe-sdk | `client/typescript/src/protocol.ts` | Add JobCreateRequest/Response, JobStatusResponse, etc. |
| soothe-sdk | `client/typescript/src/client.ts` | Add jobCreate(), jobStatus(), autopilotSubscribe() methods |
| soothe-sdk | `client/typescript/src/events.ts` | Add soothe.autopilot.* event type constants |

**New types needed**:

```typescript
// Job types
interface JobCreateRequest {
  type: 'job_create';
  goal: string;
  verification_rules?: string;
  request_id?: string;
}

interface JobCreateResponse {
  type: 'job_create_response';
  job_id: string;
  status: string;
  request_id?: string;
}

interface JobStatusResponse {
  type: 'job_status_response';
  job_id: string;
  status: string;
  active_goals: number;
  completed_goals: number;
  failed_goals: number;
  total_goals: number;
  workers: Array<{goal_id: string, loop_id: string}>;
  last_error?: string;
  request_id?: string;
}

interface JobDagResponse {
  type: 'job_dag_response';
  job_id: string;
  dag: {
    nodes: DagNode[];
    edges: DagEdge[];
  };
  request_id?: string;
}

interface DagNode {
  id: string;
  description: string;
  status: string;
  priority: number;
  depends_on: string[];
  assigned_loop_id?: string;
  steps_completed: number;
  steps_total: number;
  tool_calls: number;
  summary?: string;
  findings?: string[];
}

interface DagEdge {
  source: string;
  target: string;
}

// Autopilot subscription
interface AutopilotSubscribeResponse {
  type: 'autopilot_subscribe_response';
  client_id: string;
  subscribed: boolean;
  request_id?: string;
}
```

**Client methods**:

```typescript
// In Client class
async jobCreate(goal: string, verification_rules?: string): Promise<JobCreateResponse>;
async jobStatus(job_id: string): Promise<JobStatusResponse>;
async jobPause(job_id: string): Promise<void>;
async jobResume(job_id: string): Promise<void>;
async jobCancel(job_id: string): Promise<void>;
async jobDag(job_id: string): Promise<JobDagResponse>;
async jobGuidance(job_id: string, goal_id?: string, text: string): Promise<void>;
async autopilotSubscribe(): Promise<void>;
async autopilotUnsubscribe(): Promise<void>;
```

### Phase 2: Desktop IPC Bridge

**Goal**: Extend Electron IPC channels for RFC-228 commands.

**Files to modify**:

| File | Changes |
|------|---------|
| `src/shared/ipc.ts` | Add Channels.JobsCreate, JobsStatus, etc.; extend SootheBridge interface |
| `src/main/daemon/manager.ts` | Add jobCreate(), jobStatus(), autopilotSubscribe() methods to WSManager |
| `src/main/ipc/handlers/jobs.ts` | NEW: IPC handlers for job commands |
| `src/preload/index.ts` | Add job/autopilot methods to bridge |
| `src/main/index.ts` | Register jobs handlers |

**New IPC channels**:

```typescript
// src/shared/ipc.ts
export const Channels = {
  // ... existing channels
  JobsCreate: 'jobs:create',
  JobsStatus: 'jobs:status',
  JobsPause: 'jobs:pause',
  JobsResume: 'jobs:resume',
  JobsCancel: 'jobs:cancel',
  JobsDag: 'jobs:dag',
  JobGuidance: 'job:guidance',
  AutopilotSubscribe: 'autopilot:subscribe',
  AutopilotUnsubscribe: 'autopilot:unsubscribe',
};
```

### Phase 3: Zustand Store Extension

**Goal**: Add project, jobs, and autopilot subscription state.

**Files to modify**:

| File | Changes |
|------|---------|
| `src/renderer/state/store.ts` | Add project, jobs, autopilot state slices |

**New state structure**:

```typescript
interface StoreState {
  // ... existing state
  
  // Project state
  project: {
    path: string | null;
    name: string;
    initialized: boolean;
    loading: boolean;
  };
  
  // Jobs state
  jobs: JobSummary[];
  jobsLoading: boolean;
  jobsError?: string;
  activeJobId?: string;
  
  // Autopilot subscription
  autopilotSubscribed: boolean;
  
  // Job creation dialog
  jobCreateOpen: boolean;
  jobEditOpen: boolean;
  editingJobId?: string;
}

interface JobSummary {
  id: string;
  name: string;
  status: string;
  goal: string;
  created_at: string;
  active_goals: number;
  completed_goals: number;
  total_goals: number;
  duration_ms: number;
  last_error?: string;
}
```

### Phase 4: Project Model Implementation

**Goal**: Implement project selection and initialization.

**Files to create/modify**:

| File | Purpose |
|------|---------|
| `src/renderer/app/Header.tsx` | NEW: Project selector header |
| `src/renderer/features/project/ProjectPickerDialog.tsx` | NEW: Folder picker dialog |
| `src/renderer/features/project/ProjectInitDialog.tsx` | NEW: Initialize project dialog |
| `src/renderer/state/store.ts` | Project state mutations |
| `src/main/ipc/handlers/project.ts` | NEW: Project initialization handlers |

**Project initialization flow**:

1. User clicks project selector → opens folder picker
2. If folder lacks `.soothe/`, show init dialog
3. On confirm → create `.soothe/project.yml`, `.soothe/resources.db`
4. Load project → query jobs list from daemon

### Phase 5: Side Panel Redesign

**Goal**: Split sidebar into collapsible Chats and Jobs sections.

**Files to modify/create**:

| File | Changes |
|------|---------|
| `src/renderer/app/Sidebar.tsx` | Refactor: collapsible sections |
| `src/renderer/features/sidebar/ChatsSection.tsx` | NEW: Chats list with status colors |
| `src/renderer/features/sidebar/JobsSection.tsx` | NEW: Jobs list with duration |
| `src/renderer/features/sidebar/SectionHeader.tsx` | NEW: Collapsible header component |

**Section header pattern**:

```tsx
<Collapsible open={sectionOpen} onOpenChange={setSectionOpen}>
  <SectionHeader>
    <ChevronRight className={cn("rotate-90", !open && "rotate-0")} />
    <span>{title}</span>
    <Badge>{count}</Badge>
  </SectionHeader>
  <CollapsibleContent>
    {items.map(item => <ResourceItem key={item.id} item={item} />)}
  </CollapsibleContent>
</Collapsible>
```

**Status colors**:

```tsx
const statusColors = {
  active: 'bg-green-500',
  idle: 'bg-gray-400',
  error: 'bg-red-500',
  suspended: 'bg-yellow-500',
};
```

### Phase 6: Job Creation Dialog

**Goal**: Implement job creation/editing dialog.

**Files to create**:

| File | Purpose |
|------|---------|
| `src/renderer/features/jobs/JobCreateDialog.tsx` | NEW: Job creation form |
| `src/renderer/features/jobs/JobEditDialog.tsx` | NEW: Job editing form (pause required) |

**Dialog structure**:

```tsx
<Dialog open={jobCreateOpen} onOpenChange={setJobCreateOpen}>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Create Autopilot Job</DialogTitle>
    </DialogHeader>
    
    <div className="space-y-4">
      <Textarea
        placeholder="Describe what the autopilot should accomplish..."
        value={goal}
        onChange={setGoal}
        rows={5}
      />
      
      <Collapsible>
        <CollapsibleTrigger>
          <Button variant="ghost">Add verification rules</Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Textarea
            placeholder="Optional verification criteria..."
            value={verificationRules}
            onChange={setVerificationRules}
          />
        </CollapsibleContent>
      </Collapsible>
    </div>
    
    <DialogFooter>
      <Button variant="outline" onClick={() => setJobCreateOpen(false)}>Cancel</Button>
      <Button onClick={handleCreate}>Create</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

### Phase 7: DAG Visualization

**Goal**: Implement React Flow DAG visualization for jobs.

**Files to create**:

| File | Purpose |
|------|---------|
| `src/renderer/features/dag/DagView.tsx` | NEW: Main DAG container |
| `src/renderer/features/dag/DagNode.tsx` | NEW: Custom goal node component |
| `src/renderer/features/dag/DagToolbar.tsx` | NEW: Job controls toolbar |
| `src/renderer/features/dag/useDagData.ts` | NEW: Hook for DAG data fetching |

**Dependencies**:

```bash
npm install @xyflow/react
```

**DagNode component**:

```tsx
// Custom node showing goal info
function DagNode({ data }: { data: DagNodeData }) {
  return (
    <div className={cn(
      "p-3 rounded-lg border-2 min-w-[200px]",
      statusBorderColors[data.status]
    )}>
      <div className="font-medium truncate">{data.description}</div>
      <div className="flex items-center gap-2 mt-2">
        <Badge variant={statusBadgeVariant[data.status]}>
          {data.status}
        </Badge>
        <span className="text-sm text-muted-foreground">
          {data.steps_completed}/{data.steps_total}
        </span>
        <Badge variant="outline">{data.tool_calls} 🛠</Badge>
      </div>
      <ProgressBar value={data.steps_completed / data.steps_total} />
    </div>
  );
}
```

**DAG polling**:

```tsx
// Poll job_dag every 2 seconds while job is active
useEffect(() => {
  if (!activeJobId || jobStatus !== 'running') return;
  
  const interval = setInterval(async () => {
    const dag = await soothe().jobDag(activeJobId);
    setDagData(dag);
  }, 2000);
  
  return () => clearInterval(interval);
}, [activeJobId, jobStatus]);
```

### Phase 8: Loop Observation Room (LOR)

**Goal**: Implement readonly loop view with comment panel.

**Files to create**:

| File | Purpose |
|------|---------|
| `src/renderer/features/lor/LorView.tsx` | NEW: LOR split layout |
| `src/renderer/features/lor/LorMessageList.tsx` | NEW: Readonly message list |
| `src/renderer/features/lor/LorCommentPanel.tsx` | NEW: Comment input + history |
| `src/renderer/features/lor/CommentBadge.tsx` | NEW: Badge for cards with comments |

**LOR layout**:

```tsx
<div className="flex h-full">
  {/* Left: Readonly message list */}
  <div className="flex-1 border-r">
    <LorMessageList events={loopEvents} />
  </div>
  
  {/* Right: Comment panel */}
  <div className="w-[30%] p-4">
    <LorCommentPanel
      comments={comments}
      onAddComment={handleAddComment}
    />
  </div>
</div>
```

**Comment panel**:

```tsx
function LorCommentPanel({ comments, onAddComment }) {
  return (
    <div className="h-full flex flex-col">
      <div className="font-semibold mb-4">Observation Room</div>
      
      {/* Comment history grouped by target */}
      <div className="flex-1 overflow-auto space-y-4">
        {commentGroups.map(group => (
          <CommentGroup key={group.cardId} group={group} />
        ))}
      </div>
      
      {/* Input */}
      <Textarea
        placeholder="Add guidance..."
        value={draft}
        onChange={setDraft}
      />
      <Button onClick={() => onAddComment(draft)}>Send</Button>
    </div>
  );
}
```

**Mode determination**:

```tsx
// In TabView or similar
const isObservationMode = tab.source === 'dag-node'; // opened from DAG click
// or check if loop_id starts with 'autopilot__'
```

## Implementation Order

| Phase | Priority | Depends On |
|-------|----------|------------|
| Phase 1: TypeScript Types | High | None |
| Phase 2: Desktop IPC Bridge | High | Phase 1 |
| Phase 3: Zustand Store | Medium | Phase 2 |
| Phase 4: Project Model | Medium | Phase 2 |
| Phase 5: Side Panel | High | Phase 3 |
| Phase 6: Job Creation Dialog | High | Phase 3 |
| Phase 7: DAG Visualization | High | Phase 3, 6 |
| Phase 8: LOR | Medium | Phase 7 |

## Testing Strategy

1. Unit tests for Zustand store mutations
2. Integration tests for IPC bridge (mock daemon responses)
3. E2E tests for job creation flow
4. Manual testing with real daemon

## Dependencies to Add

```json
{
  "dependencies": {
    "@xyflow/react": "^12.0.0",
    "lucide-react": "^0.454.0",
    "@radix-ui/react-collapsible": "^1.1.0"
  }
}
```

## Success Criteria

- [ ] TypeScript client has all RFC-228 methods
- [ ] Desktop IPC bridge supports job commands
- [ ] Project selection and initialization works
- [ ] Side panel shows Chats and Jobs separately
- [ ] Job creation dialog creates jobs via daemon
- [ ] DAG visualization renders goal nodes with status
- [ ] LOR shows readonly messages + comment panel
- [ ] Comments send to daemon via job_guidance