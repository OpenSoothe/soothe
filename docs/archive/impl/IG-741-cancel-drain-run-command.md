# IG-741: Drain run_command + run_background on goal cancel

## Problem

User cancel cooperatively aborts StrangeLoop (`user_cancelled`) but does not
terminate shell children. Autopilot already drains `run_background` via
`drain_goal_runtime` (bg-logs). Interactive StrangeLoop cancel did not call
that drain, and `run_command` had no durable PID tracking at all.

## Approach

1. **soothe-nano ≥1.1.13**: While `run_command` is in flight, write
   `{workspace}/.soothe/foreground/fg-{pid}.session` (removed on exit),
   mirroring `run_background`'s `bg-{pid}.log` convention.
2. **soothe**: Extend `drain_goal_runtime` to reap both `foreground/fg-*` and
   `background/bg-*` process groups (SIGTERM → grace → SIGKILL).
3. **Wire cancel**: On StrangeLoop user cancel (runner finally + daemon cancel
   orchestrator), drain the loop workspace.

## Release note

Publish `soothe-nano` 1.1.13, then bump the host floor
`soothe-nano>=1.1.13` when ready. Until then, cancel still drains
`run_background`; `run_command` drain requires the nano session markers.

## Checklist

- [x] soothe-nano foreground session markers for in-flight `run_command`
- [x] `drain_goal_runtime` reaps fg + bg markers
- [x] StrangeLoop runner cancel finally drains workspace shells
- [x] Daemon cancel orchestrator drains workspace shells
- [x] Unit tests (drain + nano session)
- [ ] Publish soothe-nano 1.1.13 and bump host floor
