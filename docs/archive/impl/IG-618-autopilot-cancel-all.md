# IG-618: Autopilot cancel-all and job cascade

**Created**: 2026-07-16  
**Status**: Implemented  
**Related**: RFC-228, RFC-626

## Goal

CLI can stop all open autopilot work in one command; canceling a job
cancels its descendant goals.

## Changes

1. `AutopilotService.cancel_goal` cascades to the goal subtree (workers + status).
2. `AutopilotService.cancel_all_open_goals` cancels every non-terminal goal (one persist).
3. Wire `autopilot_cancel_all` RPC + client helper (local workspace client; package pin stays `>=0.9.9`).
4. CLI: `soothe autopilot cancel --all` and `cancel --job <id>` (single `goal_id` keeps cascade).
