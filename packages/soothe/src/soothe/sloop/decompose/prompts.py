"""THREAD prompt copy for ``decompose_task`` vs ``write_todos`` (RFC-904 §5.1)."""

from __future__ import annotations

DECOMPOSITION_VS_TODOS_BLOCK = """\
DECOMPOSITION vs TODOS:
- decompose_task: durable StepDAG children; ends this thread; CE reconciles.
- write_todos: ephemeral checklist inside this step; keep working after.
- Prefer complete if you can finish now. Prefer decompose_task only for
  schedulable split. Prefer write_todos only for in-thread tracking.
- When APPROVED PLAN is present: treat Changes as the preferred child-step
  outline — call decompose_task to schedule them rather than re-planning from
  scratch or finishing everything in this one thread.
"""

WRITE_TODOS_SYSTEM_ADDENDUM = """\
## write_todos (intra-step only)

`write_todos` tracks progress **inside the current execution step**.
It does NOT create StrangeLoop steps and does NOT change the goal StepDAG.

Use write_todos when:
- This step needs 3+ tool actions you will run yourself in this thread
- You want a live checklist for the TUI / your own focus
- You may revise the list as you discover work mid-step

Do NOT use write_todos when:
- Work should become separate schedulable steps → call decompose_task instead
- The step is trivial (a few tool calls) → just execute and finish
- You are about to end the thread by decomposing — skip todos; decompose

write_todos is never terminal. After updating todos, continue working.
Mark items completed as you finish them. Deliver the step result as normal
assistant content / tool outcomes; marking todos done is not step completion.
"""

WRITE_TODOS_TOOL_DESCRIPTION = """\
Create or replace the todo list for THIS step's in-thread work only.
Args: todos: [{content, status}] with status pending|in_progress|completed.
Does not spawn StepDAG children. For cross-step decomposition use decompose_task.
"""

DECOMPOSE_TASK_TOOL_DESCRIPTION = """\
Propose child steps for the Context Engine StepDAG when this step cannot
(or should not) be finished in this thread alone.

Use when subtasks need their own threads, dependencies, parallelism, or
independent failure/retry. This call is TERMINAL for this thread: after
reconcile, children are dispatched separately.

Do NOT use for a personal checklist of work you will still do here —
use write_todos for that.

Args: task, subtasks[{description, full_description, expected_output,
execution_hint, depends_on_local}]. Cross-step deps outside this proposal
are inferred by reconcile; only express in-subtree depends_on_local.
"""
