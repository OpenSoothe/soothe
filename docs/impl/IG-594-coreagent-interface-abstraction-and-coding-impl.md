# IG-594: CoreAgent Interface Abstraction and Coding Implementation

## Goal

Make StrangeLoop depend on a stable Layer-1 core-agent protocol, with the
existing filesystem/tooling runtime represented explicitly as `CodingCoreAgent`.

## Scope

- Harden `CoreAgentProtocol` with capability and runtime-state access surfaces.
- Keep behavior unchanged for current coding workflows.
- Move loop/runner typing and coupling to protocol-level imports.
- Keep compatibility aliases so existing call sites continue to work.
- Add runtime-kind selection in factory/builder, defaulting to coding.

## Non-Goals

- Implementing a second non-coding core-agent runtime in this change.
- Rewriting execute/interrupt semantics in loop engine.

## Rollout

1. Add protocol methods + capability model; adapt current implementation.
2. Repoint loop/runner/synthesis typing to protocol.
3. Introduce explicit `CodingCoreAgent` name with `CoreAgent` compatibility alias.
4. Add factory runtime-kind selection (`coding` default).
5. Replace ad-hoc capability probing with protocol capability metadata.
6. Validate with focused loop/executor tests and final verification.

## Risks

- Clarification interrupt resume depends on graph-state shape.
- Type-only inversion can hide runtime assumptions if protocol remains too thin.

