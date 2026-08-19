"""StrangeLoop THREAD prompts for do-or-decompose (RFC-904).

User-facing copy avoids host jargon (StepDAG / CE / StrangeLoop). Prefer
``task`` / ``thread`` / ``subtasks`` so the model is not asked to reason about
internal graph types. Kept under ``soothe.sloop.prompts``.
"""

from __future__ import annotations

DECOMPOSITION_VS_TODOS_BLOCK = """\
Before acting, judge this EXECUTION TASK:

FINISH HERE when ALL of:
- One clear deliverable you can finish with tools in this thread
- No need for parallel independent workstreams
- A failed sub-part would not need its own later retry as a separate task

SPLIT (call decompose_task, then STOP) when ANY of:
- Multiple deliverables or phases that should run as separate tasks later
- Independent work that can run in parallel or has hard dependencies
- A subtask should fail/retry without redoing the rest
- You would otherwise build a long write_todos list that is really a plan

Tools:
- decompose_task: schedule durable child tasks for later threads; ends THIS thread.
- write_todos: checklist only while you keep working in THIS thread.

decompose_task is TERMINAL: after it returns, do not keep executing.
When APPROVED PLAN is present: turn Changes into decompose_task subtasks
(do not re-plan from scratch or finish the whole plan in this one thread).
"""

WRITE_TODOS_SYSTEM_ADDENDUM = """\
## write_todos (this thread only)

`write_todos` tracks progress **while you keep working on this EXECUTION TASK**.
It does NOT schedule later tasks and does NOT change the durable task graph.

Use write_todos when:
- This thread needs 3+ tool actions you will run yourself here
- You want a live checklist for the TUI / your own focus
- You may revise the list as you discover work mid-thread

Do NOT use write_todos when:
- Work should become separate later tasks → call decompose_task instead
- The task is trivial (a few tool calls) → just execute and finish
- You are about to call decompose_task — skip todos; decompose and stop

write_todos is never terminal. After updating todos, continue working.
Mark items completed as you finish them. Deliver the result as normal
assistant content / tool outcomes; marking todos done is not task completion.
"""

WRITE_TODOS_TOOL_DESCRIPTION = """\
Create or replace the todo list for THIS thread's in-progress work only.
Args: todos: [{content, status}] with status pending|in_progress|completed.
Does not schedule later tasks. For splitting into later tasks use decompose_task.
"""

DECOMPOSE_TASK_TOOL_DESCRIPTION = """\
First decide: can this EXECUTION TASK finish in this thread, or must it split?

Call decompose_task when the work is complex in a *schedulable* sense:
multiple deliverables/phases, parallel workstreams, hard dependencies, or
independent failure/retry per subtask. Propose child tasks for later threads;
this call is TERMINAL for this thread (children run separately afterward).

Do NOT call when you can finish one clear deliverable here with tools.
Do NOT use as a personal checklist — use write_todos for that.

Args: task, subtasks[{description, full_description, expected_output,
execution_hint, depends_on_local}]. Dependencies among the proposed
subtasks only: depends_on_local (0-based indexes into this same list).
"""

APPROVED_PLAN_EXECUTE_HINT = (
    "Operator approved this solution report. Prefer `decompose_task` to turn "
    "Changes into child tasks for later threads; execute only work that stays in "
    "this thread. Do not re-litigate the Solution unless blocked."
)

_ROOT_DO_OR_DECOMPOSE_LINES: tuple[str, ...] = (
    "- You own the full goal in this thread: first judge whether to finish here "
    "or split. If it needs multiple later tasks, call decompose_task and stop; "
    "otherwise finish it in this thread",
)

_CHILD_DO_OR_DECOMPOSE_LINES: tuple[str, ...] = (
    "- Prefer finish this EXECUTION TASK in this thread; call decompose_task "
    "only if it still needs a further split into later tasks",
)


def do_or_decompose_instruction_lines(*, is_dag_root: bool) -> list[str]:
    """Return INSTRUCTIONS bullets for root vs child durable tasks."""
    if is_dag_root:
        return list(_ROOT_DO_OR_DECOMPOSE_LINES)
    return list(_CHILD_DO_OR_DECOMPOSE_LINES)


__all__ = [
    "APPROVED_PLAN_EXECUTE_HINT",
    "DECOMPOSITION_VS_TODOS_BLOCK",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "WRITE_TODOS_SYSTEM_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "do_or_decompose_instruction_lines",
]
