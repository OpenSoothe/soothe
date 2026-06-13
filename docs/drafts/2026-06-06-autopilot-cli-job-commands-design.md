# Autopilot CLI Job Commands Design

**Date**: 2026-06-06
**Status**: Draft
**Related**: RFC-228 (Autopilot Job IPC), RFC-222 (Autopilot Architecture)

## Problem Statement

Current `soothe autopilot list` shows ALL GoalEngine goals including autopilot-created subgoals, making it hard for users to track their submitted jobs. RFC-228 defines "Job" as a root Goal (parent_id=None), but CLI doesn't expose this distinction.

Additionally, there's no way to view DAG structure of a job from CLI - users can only see individual goal details.

## Design Goals

1. `soothe autopilot list` → Show only user-submitted jobs (root goals)
2. `soothe autopilot job <job_id>` → Show job status + DAG tree visualization
3. Keep existing `soothe autopilot goal <goal_id>` for any goal details

## Architecture Context

### Terminology (per RFC-228)

| Term | Definition | Implementation |
|------|------------|----------------|
| **Job** | Root Goal submitted to AutopilotService | `Goal` with `parent_id=None` |
| **Goal** | Node in GoalEngine DAG (root or subgoal) | `Goal` model in `goal_engine/models.py` |
| **DAG** | Hierarchical goal structure under a job | `depends_on` relationships |

### Existing Backend Support

- GoalEngine stores `parent_id` field on each Goal
- AutopilotService has `dag_snapshot(root_goal_id)` method (RFC-228 §295-300)
- Daemon has WebSocket handler `_handle_job_dag` (RFC-228)
- HTTP REST endpoint `/api/v1/autopilot/goals` exists but returns all goals

## Implementation Plan

### 1. SDK Changes (`soothe_sdk/client/autopilot_http.py`)

Add two methods:

```python
def list_jobs(self) -> dict[str, Any]:
    """List root goals (jobs) only."""
    return self._request("GET", "/api/v1/autopilot/jobs")

def get_job_dag(self, job_id: str) -> dict[str, Any]:
    """Get job status and DAG snapshot."""
    return self._request("GET", f"/api/v1/autopilot/jobs/{job_id}")
```

### 2. Daemon HTTP REST Changes (`soothe_daemon/channels/http_rest.py`)

Add endpoints:

```python
@self._app.get("/api/v1/autopilot/jobs")
async def autopilot_list_jobs() -> dict[str, Any]:
    """List root goals (jobs) only."""
    service = self._require_autopilot_service()
    goals = await service.list_goals()
    jobs = [g for g in goals if g.parent_id is None]
    return {
        "jobs": [j.model_dump(mode="json") for j in jobs],
        "source": "autopilot_service",
    }

@self._app.get("/api/v1/autopilot/jobs/{job_id}")
async def autopilot_get_job(job_id: str) -> dict[str, Any]:
    """Get job status with DAG snapshot."""
    service = self._require_autopilot_service()
    job = await service.get_goal(job_id)
    if not job or job.parent_id is not None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    dag = await service.dag_snapshot(job_id)
    return {
        "job": job.model_dump(mode="json"),
        "dag": dag,
        "source": "autopilot_service",
    }
```

### 3. CLI Changes (`soothe_cli/cli/commands/autopilot_cmd.py`)

#### 3.1 Refine `list` Command

```python
@app.command("list")
def list_jobs(
    status_filter: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List jobs (root goals) from the daemon autopilot."""
    client = _require_daemon_http()
    payload = client.list_jobs()
    jobs = payload.get("jobs") or []
    if not jobs:
        typer.echo("No jobs found.")
        return

    for j in jobs:
        if status_filter and j.get("status", "") != status_filter:
            continue
        sid = j.get("id", "?")[:8]
        sdesc = preview_first(j.get("description", ""), 60)
        sstat = j.get("status", "pending")
        spri = j.get("priority", 50)
        typer.echo(f"  [{sid}] {sstat:10s} pri={spri:3d}  {sdesc}")
```

#### 3.2 Add `job` Command

```python
@app.command("job")
def show_job(
    job_id: str = typer.Argument(..., help="Job ID to show details and DAG."),
) -> None:
    """Show job status and DAG tree."""
    client = _require_daemon_http()
    payload = client.get_job_dag(job_id)
    job = payload.get("job")
    dag = payload.get("dag")
    
    if not job:
        typer.echo(f"Job '{job_id}' not found.", err=True)
        raise typer.Exit(1)

    # Job header
    typer.echo(f"Job ID:          {job.get('id')}")
    typer.echo(f"Status:          {job.get('status', 'pending')}")
    typer.echo(f"Priority:        {job.get('priority', 50)}")
    if job.get("workspace"):
        typer.echo(f"Workspace:       {job['workspace']}")
    typer.echo(f"Created:         {job.get('created_at', '')}")
    
    # DAG stats
    nodes = dag.get("nodes", [])
    active = sum(1 for n in nodes if n.get("status") == "active")
    completed = sum(1 for n in nodes if n.get("status") == "completed")
    typer.echo(f"Active goals:    {active}")
    typer.echo(f"Completed goals: {completed}")
    typer.echo(f"Total goals:     {len(nodes)}")
    
    typer.echo("\nDAG:")
    _render_dag_tree(dag, job_id)
```

#### 3.3 ASCII Tree Formatter

```python
def _render_dag_tree(dag: dict, root_id: str) -> None:
    """Render DAG as ASCII tree."""
    nodes = {n["id"]: n for n in dag.get("nodes", [])}
    edges = dag.get("edges", [])
    
    # Build children map
    children: dict[str, list[str]] = {}
    for edge in edges:
        src = edge["source"]
        tgt = edge["target"]
        if src not in children:
            children[src] = []
        children[src].append(tgt)
    
    def render_node(goal_id: str, indent: str = "", is_last: bool = True) -> None:
        node = nodes.get(goal_id)
        if not node:
            return
        
        prefix = indent + ("└─ " if is_last else "├─ ") if indent else ""
        status = node.get("status", "pending")
        desc = preview_first(node.get("description", ""), 50)
        typer.echo(f"{prefix}{goal_id[:8]} ({status}) \"{desc}\"")
        
        # Render children
        child_ids = children.get(goal_id, [])
        for i, child_id in enumerate(child_ids):
            child_indent = indent + ("    " if is_last else "│   ")
            render_node(child_id, child_indent, i == len(child_ids) - 1)
    
    render_node(root_id)
```

## Output Examples

### `soothe autopilot list`

```
$ soothe autopilot list
[43caba4a] completed   pri=50  "generate deep wiki of this project"
[fae9b5a3] suspended   pri=50  "List all Python files in packages directory"
```

### `soothe autopilot job <job_id>`

```
$ soothe autopilot job fae9b5a3
Job ID:          fae9b5a3
Status:          suspended
Priority:        50
Workspace:       /Users/chenxm/Workspace/soothe
Created:         2026-06-06 14:25:12
Active goals:    1
Completed goals: 2
Total goals:     3

DAG:
fae9b5a3 (suspended) "List all Python files in packages directory"
├─ e5f6g7h8 (completed) "Explore packages directory structure"
└─ i9j0k1l2 (active)    "Count .py files in each package"
```

### `soothe autopilot goal <goal_id>` (unchanged)

```
$ soothe autopilot goal e5f6g7h8
ID:          e5f6g7h8
Description: Explore packages directory structure
Status:      completed
Priority:    80
Depends On:  fae9b5a3
```

## Error Handling

| Scenario | Response |
|----------|----------|
| Job not found | HTTP 404, CLI: "Job '{id}' not found" |
| Goal ID provided to `job` command | HTTP 404 (parent_id != None), CLI: "Job '{id}' not found" |
| Daemon not running | CLI: "Daemon not running. Start with 'soothed start'." |

## Testing

- Unit tests for SDK `list_jobs()` and `get_job_dag()`
- Unit tests for daemon HTTP endpoints
- Unit tests for CLI ASCII tree formatter
- Integration test: submit job → list → verify job appears → job command → verify DAG

## Migration Notes

- Existing `soothe autopilot list` users will see fewer items (only root goals)
- This is the intended behavior per RFC-228
- Users can still access subgoals via `soothe autopilot goal <goal_id>`

## Out of Scope

- WebSocket IPC commands (already implemented per RFC-228)
- Desktop app integration (RFC-700)
- StrangeLoop loop management (separate concept, uses `soothe loop` commands)