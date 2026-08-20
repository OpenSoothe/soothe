# IG-755: Unified traced LLM invocation

**Created**: 2026-08-20
**Status**: Verification
**Packages**: `soothe`, `soothe-autopilot`, `soothe-daemon`
**Related**: `soothe-nano` 1.2.5 traced LLM interfaces (structured-output
callbacks via public `ainvoke`)

---

## Goal

Require `soothe-nano>=1.2.5` and route every direct chat-model invocation
through nano's traced interfaces so enabled Langfuse observability captures
plain and structured calls consistently. LangGraph graph/agent invocations
continue to inherit their already-traced graph `RunnableConfig`.

## Design rules

1. Plain direct calls use `soothe_nano.llm.ainvoke_traced`.
2. Structured direct calls use
   `soothe_nano.llm.ainvoke_structured_traced`; callers validate returned
   dictionaries with their Pydantic response model.
3. Every runtime-owned direct caller receives the process `SootheConfig`.
   Calls without config remain supported for isolated tests but only carry
   standard metadata because no Langfuse credentials are available.
4. Streaming synthesis remains on `BaseChatModel.astream` with its existing
   merged Langfuse graph config because nano 1.2.4 has no traced streaming
   helper.
5. Intake keeps its configured structured-method order while using nano's
   traced config builder; this preserves provider compatibility.

## Work items

- [x] Raise `soothe-nano` floors to 1.2.5 and regenerate `uv.lock`
- [x] Migrate host direct plain and structured calls
- [x] Migrate daemon direct plain and structured calls
- [x] Migrate Autopilot direct plain and structured calls and propagate config
- [ ] Add tracing-focused unit coverage and run final verification
