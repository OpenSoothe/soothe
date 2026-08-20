# IG-754: StrangeLoop Eval Thread

> Implementation guide for [RFC-905](../specs/RFC-905-sloop-eval-thread.md).
> Status: **In progress**.

## Scope

Implement Eval as an engine-injected `kind=eval` StepNode:

1. Extend StepDAG and runtime step schemas with `eval` and structured
   `StepCloseReport` evidence.
2. Make ROOT_EVAL insert an Eval step at action-tree green when required.
3. Execute Eval in its own CoreAgent thread with readonly tools plus
   `decompose_task`.
4. Reject Eval proposals that are not in-scope and necessary.
5. Add configuration, prompts, tests, and template synchronization.

## Implementation slices

| Slice | Change | Exit criteria |
|-------|--------|---------------|
| Schema | `kind=eval`, close-report model, action-tree helpers | Unit tests cover require/skip |
| Policy | Eval middleware and prompt | Only read tools + `decompose_task` visible |
| Execution | Fresh eval thread, evidence envelope, structured close report | Eval and action paths remain isolated |
| Routing | ROOT_EVAL insert/skip, reconcile scoped children | In-scope continuation dispatches; complete Eval finalizes |
| Verification | Focused tests, final repository verification | All checks green |

## Invariants

- Eval nodes are engine-created; worker proposals create `action` children.
- Eval never receives write, shell, process, subagent, or mutating MCP tools.
- Early-exit judgment is structured model output, never keyword matching.
- A completed latest Eval with no children finalizes without inserting another.
- A decomposed latest Eval requires a later coverage round after its children.
- Failed action leaves never finalize successfully through Eval.

## Files

- `packages/soothe/src/soothe/context/{models,decomposition}.py`
- `packages/soothe/src/soothe/sloop/eval/`
- `packages/soothe/src/soothe/sloop/stations/decompose/{dispatch,root_eval,reconcile_node}.py`
- `packages/soothe/src/soothe/sloop/engine/execute/executor.py`
- `packages/soothe/src/soothe/coreagent/builder.py`
- `packages/soothe/src/soothe/config/models.py`
- `config/soothe.template.yml` and packaged template copy
- package-local unit tests
