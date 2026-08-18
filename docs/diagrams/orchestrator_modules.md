# StrangeLoop orchestrator modules

Canonical view: [`orchestrator_modules.mmd`](orchestrator_modules.mmd).

Package: `soothe.sloop.orchestrator` (unified in IG-745). Leaf modules by concern:

| Module | Concern | Key exports |
|--------|---------|-------------|
| `builder.py` | Compile LangGraph | `build_strange_loop_graph` |
| `runner.py` | Invoke / resume | `invoke_strange_loop_graph`, `build_loop_graph_invoke_config` |
| `stations.py` | Station IDs + graph channels | station constants, `LoopGraphState`, `PLAN_ROUTE_*` |
| `routing.py` | Conditional edges | `route_after_*` (`route_by_intent` alias) |
| `node_base.py` | Node lifecycle | `LoopNode`, `wrap_node`, `RouteDecision`, `GuardOutcome`, `NodeResult` |
| `runtime_context.py` | Per-run mutable bundle | `LoopRuntimeContext`, `LoopPhaseScratch` |
| `continuation.py` | Fresh / mid-loop intake policy | `is_fresh_goal`, mid-loop helpers, bypass assessments |
| `checkpoint.py` | Thread isolation + checkpointer | `strange_loop_thread_id`, `intake_only_invoke_config`, `core_agent_checkpointer` |

Package root (`__init__.py`) lazily exports only `LoopRuntimeContext` (import-cycle fence).

Related graph diagrams: [`strange_loop_stem.mmd`](strange_loop_stem.mmd),
[`strange_loop_graph_nodes.md`](strange_loop_graph_nodes.md),
[`strange_loop_graph.mmd`](strange_loop_graph.mmd).
