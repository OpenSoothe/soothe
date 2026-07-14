# IG-353: Planner performance prototype

## Purpose

Track work for optimizing AgentLoop Plan-phase latency and wasted iterations, per RFC-604 (`LLMPlanner`).

## Phases (implementation order)

| Phase | Description | Status |
|-------|-------------|--------|
| A | Plan-phase timings (`assess_ms`, `plan_gen_ms`) + approximate `prompt_chars`; INFO log line | Done |
| F | Align docstrings with RFC-604 (two LLM calls when status≠done) | Done |
| D | Stuck-loop / paraphrase completion heuristics | Pending user confirm |
| C | Optional prompt caps for Plan human message | Pending user confirm |
| B+E | Unified structured output + config flag | Pending user confirm |

## References

- [`packages/soothe/src/soothe/cognition/agent_loop/core/planner.py`](../../packages/soothe/src/soothe/cognition/agent_loop/core/planner.py)
- [`packages/soothe/src/soothe/core/resolver/__init__.py`](../../packages/soothe/src/soothe/core/resolver/__init__.py) (`resolve_planner` prefers `fast` model)
