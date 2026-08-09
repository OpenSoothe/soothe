# IG-733: Autopilot Cognition Intake

> **Note:** Package path is `soothe.autopilot.intake` (renamed from the
> provisional `cognition` name used while drafting this IG).

## Goal

Make Autopilot intake explicit: **GOAL.md contract**, **user guidance**, and
**channel guidance** flow through `soothe.autopilot.intake` into
ContextEngine goal state, then dispatch to StrangeLoop workers. Guidance never
spawns or injects goals.

## Pipeline

```text
GOAL.md / user guidance / channel guidance
  → autopilot.intake
  → ContextEngine (guidance_accumulated / job GOAL.md artifact)
  → AutopilotService dispatch (collect → operator_guidance on bundle)
  → StrangeLoop exec
```

## Package (`soothe.autopilot.intake`)

| Module | Role |
|--------|------|
| `contract.py` | Job-scoped `jobs/{id}/GOAL.md` write/load (from former `jobs/goal_md.py`) |
| `guidance.py` | Absorb façade (`user` / `channel`) + `collect_operator_guidance` |
| `models.py` | `GuidanceSource`, `GuidanceScope` |

CE remains the durable store. `absorb_guidance` records a `source` tag
(`user` \| `channel` \| `system`).

## CLI

`soothe autopilot guide JOB_ID TEXT [--goal GOAL_ID]` → WS `job_guidance` →
`absorb_user_guidance` → CE.

## Non-goals (this pass)

- No ChannelManager auto-bind of inbound chat to jobs
- No relocating monitor intake, rail, workers, or dispatch projector
- No goal inject from guidance text

## Related

- RFC-228 (`job_guidance`)
- IG-702 (job GOAL.md artifact)
- IG-705 (one-level layout; `cognition/` peer package)
