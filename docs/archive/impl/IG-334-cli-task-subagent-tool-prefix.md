# IG-334: CLI Task subgraph tool & assistant prefix

## Goal

Headless CLI should label tools and assistant prose that originate inside a Task delegation:

- Tool row: `⚙ [Task(<subagent_type>):<task_tool_call_id>] DisplayName(args) -> ✓ …`
- Assistant text (when shown): leading `● [Task(<subagent_type>):<task_tool_call_id>] …`

## Approach

- Track FIFO `(task_tool_call_id, subagent_type)` when the **main** graph emits the `task` tool call.
- On first unseen LangGraph stream `namespace` tuple for subgraph chunks, bind that namespace to the next queued spawn (parallel tasks: order-sensitive).
- Resolve longest-prefix binding for nested namespaces.

## Verification

- `./scripts/verify_finally.sh`
