# StrangeLoop LangGraph — Full Edge Dump (IG-663)

Auto-generated from ``build_strange_loop_graph()``.
Canonical architecture: [`strange_loop_stem.mmd`](strange_loop_stem.mmd) /
[`strange_loop_graph_nodes.md`](strange_loop_graph_nodes.md).

Regenerate: ``python scripts/visualize_strange_loop_graph.py``

## Nodes

- `__start__`
- `intake`
- `enter_loop`
- `delegate`
- `check_limits`
- `begin_iteration`
- `gather_evidence`
- `evaluate`
- `generate_plan`
- `finalize`
- `commit_plan`
- `validate_plan`
- `execute`
- `record_progress`
- `await_user`
- `__end__`

## All edges

Solid arrows in Mermaid/SVG are unconditional; dashed are conditional.

- `__start__` → `intake`
- `await_user` → `__end__`
- `await_user` → `delegate`
- `await_user` → `evaluate`
- `await_user` → `execute`
- `await_user` → `generate_plan`
- `begin_iteration` → `gather_evidence`
- `check_limits` → `__end__`
- `check_limits` → `begin_iteration`
- `commit_plan` → `__end__`
- `commit_plan` → `validate_plan`
- `delegate` → `__end__`
- `delegate` → `await_user`
- `delegate` → `finalize`
- `delegate` → `generate_plan`
- `enter_loop` → `__end__`
- `enter_loop` → `commit_plan`
- `enter_loop` → `delegate`
- `enter_loop` → `gather_evidence`
- `evaluate` → `await_user`
- `evaluate` → `commit_plan`
- `evaluate` → `finalize`
- `evaluate` → `generate_plan`
- `execute` → `__end__`
- `execute` → `await_user`
- `execute` → `check_limits`
- `execute` → `record_progress`
- `gather_evidence` → `commit_plan`
- `gather_evidence` → `evaluate`
- `gather_evidence` → `generate_plan`
- `generate_plan` → `await_user`
- `generate_plan` → `commit_plan`
- `generate_plan` → `finalize`
- `generate_plan` → `generate_plan`
- `intake` → `enter_loop`
- `record_progress` → `__end__`
- `record_progress` → `check_limits`
- `record_progress` → `finalize`
- `validate_plan` → `__end__`
- `validate_plan` → `execute`
- `finalize` → `__end__`
