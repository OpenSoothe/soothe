"""StrangeLoop THREAD prompts for do-or-decompose (RFC-904).

Split by message role:
- **System** (``THREAD_POLICY_SYSTEM_ADDENDUM``): stable finish-vs-split +
  write_todos + search hygiene.
- **Tool schemas**: authoritative ``decompose_task`` / ``write_todos`` contracts.
- **User**: instance work (EXECUTION TASK, evidence, EXPECTED OUTPUT) plus a
  one-line finish/split reminder — not a second copy of the policy.

Avoid host jargon (StepDAG / CE / StrangeLoop). Prefer task / thread / subtasks.
"""

from __future__ import annotations

THREAD_POLICY_SYSTEM_ADDENDUM = """\
## This thread: finish vs split

Before tools, decide whether this EXECUTION TASK finishes here or must split.

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

## write_todos (this thread only)

`write_todos` tracks progress while you keep working on this EXECUTION TASK.
It does NOT schedule later tasks.

Use write_todos for a live in-thread checklist (3+ tool actions). Do NOT use it
to plan later tasks — call decompose_task instead. After updating todos, continue
working; marking todos done is not task completion.

## Tool use hygiene

- Prefer one broad native search (grep/glob) then targeted reads; avoid repeated
  equivalent scans.
- Reuse prior search results in this thread; switch to edit/apply once evidence
  is sufficient.
"""

# Backward-compatible alias (tests / older imports).
WRITE_TODOS_SYSTEM_ADDENDUM = THREAD_POLICY_SYSTEM_ADDENDUM

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

_ROOT_USER_HINT = (
    "- Own the full goal here: finish in this thread, or call decompose_task and stop "
    "if it needs multiple later tasks"
)
_CHILD_USER_HINT = (
    "- Prefer finish this EXECUTION TASK here; call decompose_task only if it still "
    "needs a further split into later tasks"
)


def user_finish_or_split_hint_lines(*, is_dag_root: bool) -> list[str]:
    """One-line user reminder (policy lives in system + tool schemas)."""
    if is_dag_root:
        return [_ROOT_USER_HINT]
    return [_CHILD_USER_HINT]


# Deprecated name: prefer ``user_finish_or_split_hint_lines``.
def do_or_decompose_instruction_lines(*, is_dag_root: bool) -> list[str]:
    """Alias for ``user_finish_or_split_hint_lines``."""
    return user_finish_or_split_hint_lines(is_dag_root=is_dag_root)


__all__ = [
    "APPROVED_PLAN_EXECUTE_HINT",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "THREAD_POLICY_SYSTEM_ADDENDUM",
    "WRITE_TODOS_SYSTEM_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "do_or_decompose_instruction_lines",
    "user_finish_or_split_hint_lines",
]
