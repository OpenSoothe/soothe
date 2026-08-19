# StrangeLoop LangGraph — Full Edge Dump

Auto-generated from ``build_strange_loop_graph()``.
Canonical architecture: [`strange_loop_stem.mmd`](strange_loop_stem.mmd) /
[`strange_loop_graph_nodes.md`](strange_loop_graph_nodes.md).
Orchestrator modules: [`orchestrator_modules.md`](orchestrator_modules.md).

Regenerate: ``python scripts/visualize_strange_loop_graph.py``

## Nodes

- `__start__`
- `intake`
- `enter_loop`
- `delegate`
- `dispatch`
- `execute`
- `record_progress`
- `reconcile`
- `root_eval`
- `finalize`
- `await_user`
- `__end__`

## All edges

Solid arrows in Mermaid/SVG are unconditional; dashed are conditional.

- `__start__` → `intake`
- `await_user` → `__end__`
- `await_user` → `delegate`
- `await_user` → `dispatch`
- `await_user` → `execute`
- `delegate` → `__end__`
- `delegate` → `await_user`
- `delegate` → `dispatch`
- `delegate` → `finalize`
- `dispatch` → `__end__`
- `dispatch` → `execute`
- `dispatch` → `root_eval`
- `enter_loop` → `__end__`
- `enter_loop` → `delegate`
- `enter_loop` → `dispatch`
- `execute` → `__end__`
- `execute` → `await_user`
- `execute` → `record_progress`
- `intake` → `enter_loop`
- `reconcile` → `dispatch`
- `reconcile` → `root_eval`
- `record_progress` → `__end__`
- `record_progress` → `finalize`
- `record_progress` → `reconcile`
- `root_eval` → `dispatch`
- `root_eval` → `finalize`
- `finalize` → `__end__`
