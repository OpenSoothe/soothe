# soothe-autopilot

Goal-driven orchestration layer for [Soothe](https://github.com/mirasoth/soothe) —
24/7 autonomous agents.

`soothe-autopilot` sits **above** the `soothe` host package and owns:

- **AutopilotService** — goal scheduling, loop-pool dispatch, lineage reuse
- **AutopilotMonitor** — DAG verification, dreaming coordination
- **Rails** — LoopRail recipes, guards, interpreters, built-in rails
- **Verify** — consensus, backoff reasoning, job maturity, goal-DAG verification
- **Intake** — operator guidance absorption, scope classification
- **Dispatch** — goal context projection and durability
- **Notify** — job lifecycle notification routing

It depends one-way on `soothe` (StrangeLoop, ContextEngine, config, events,
runner) plus `soothe-sdk` and `soothe-nano`. The `soothe` host never imports
`soothe_autopilot`.
