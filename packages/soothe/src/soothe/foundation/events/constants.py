"""Centralized event type string constants for Soothe system.

Client-facing: ``soothe.<domain>.<component>.<action>`` (RFC-0015).
Internal (daemon/worker only, never WebSocket broadcast):
``soothe.internal.<component>.<action>`` (IG-435).
"""

from __future__ import annotations

# ============================================================================
# INTERNAL NAMESPACE (soothe.internal.*) — never broadcast to clients
# ============================================================================

# Iteration
ITERATION_STARTED = "soothe.internal.iteration.started"
ITERATION_COMPLETED = "soothe.internal.iteration.completed"

# Checkpoint
CHECKPOINT_SAVED = "soothe.internal.checkpoint.saved"
CHECKPOINT_ANCHOR_CREATED = "soothe.internal.checkpoint.anchor.created"

# Recovery
RECOVERY_RESUMED = "soothe.internal.recovery.resumed"

# Loop lifecycle
LOOP_CREATED = "soothe.internal.loop.created"
LOOP_STARTED = "soothe.internal.loop.started"
LOOP_DETACHED = "soothe.internal.loop.detached"
LOOP_REATTACHED = "soothe.internal.loop.reattached"
LOOP_COMPLETED = "soothe.internal.loop.completed"

# Control-plane replay marker (prefer wire ``replay_complete`` envelope to clients)
REPLAY_COMPLETE = "replay_complete"

# Memory protocol
MEMORY_RECALLED = "soothe.internal.memory.recalled"
MEMORY_STORED = "soothe.internal.memory.stored"

# Policy protocol
POLICY_CHECKED = "soothe.internal.policy.checked"
POLICY_DENIED = "soothe.internal.policy.denied"

# Daemon
DAEMON_HEARTBEAT = "soothe.internal.daemon.heartbeat"

# Plugin lifecycle
PLUGIN_LOADED = "soothe.internal.plugin.loaded"
PLUGIN_FAILED = "soothe.internal.plugin.failed"
PLUGIN_UNLOADED = "soothe.internal.plugin.unloaded"

# Plan internals
PLAN_DAG_SNAPSHOT = "soothe.internal.plan.dag_snapshot"
PLAN_BATCH_STARTED = "soothe.internal.plan.batch.started"

# Skill internals
SKILL_BODY_LOADED = "soothe.internal.skill.body.loaded"

# MCP internals
MCP_LIST_CHANGED = "soothe.internal.mcp.list_changed"
MCP_TOOL_TIMEOUT = "soothe.internal.mcp.tool.timeout"

# Branch internals
BRANCH_ANALYZED = "soothe.internal.branch.analyzed"
BRANCH_PRUNED = "soothe.internal.branch.pruned"

# Autopilot internals (DETAILED)
AUTOPILOT_GOAL_VALIDATED = "soothe.internal.autopilot.goal.validated"
AUTOPILOT_SEND_BACK = "soothe.internal.autopilot.feedback.sent"
AUTOPILOT_RELATIONSHIP_DETECTED = "soothe.internal.autopilot.relationship.detected"
AUTOPILOT_CHECKPOINT_SAVED = "soothe.internal.autopilot.checkpoint.saved"

# ============================================================================
# CLIENT-FACING (soothe.<domain>.*)
# ============================================================================

# Goal cognition
GOAL_CREATED = "soothe.cognition.goal.created"
GOAL_COMPLETED = "soothe.cognition.goal.completed"
GOAL_FAILED = "soothe.cognition.goal.failed"
GOAL_REMOVED = "soothe.cognition.goal.removed"
GOAL_DECOMPOSED = "soothe.cognition.goal.decomposed"
GOAL_BATCH_STARTED = "soothe.cognition.goal.batch.started"
GOAL_REPORT = "soothe.cognition.goal.reported"
GOAL_DIRECTIVES_APPLIED = "soothe.cognition.goal.directives.applied"
GOAL_DEFERRED = "soothe.cognition.goal.deferred"

# Autopilot mode switching
AUTOPILOT_MODE_SWITCHED = "soothe.cognition.autopilot.mode_switched"

# Intent classification (IG-518)
INTENT_CLASSIFIED = "soothe.cognition.intent.classified"

# Plan cognition (client UX)
PLAN_CREATED = "soothe.cognition.plan.created"
PLAN_REFLECTED = "soothe.cognition.plan.reflected"

# StrangeLoop cognition
STRANGE_LOOP_STARTED = "soothe.cognition.strange_loop.started"
STRANGE_LOOP_COMPLETED = "soothe.cognition.strange_loop.completed"
STRANGE_LOOP_STEP_STARTED = "soothe.cognition.strange_loop.step.started"
STRANGE_LOOP_STEP_QUEUED = "soothe.cognition.strange_loop.step.queued"
STRANGE_LOOP_STEP_COMPLETED = "soothe.cognition.strange_loop.step.completed"
STRANGE_LOOP_PLAN_DECISION = "soothe.cognition.strange_loop.plan.decision"
STRANGE_LOOP_PLAN_PHASE = "soothe.cognition.strange_loop.plan.phase"
STRANGE_LOOP_REASONED = "soothe.cognition.strange_loop.reasoned"
STRANGE_LOOP_CONTEXT_COMPACTED = "soothe.cognition.strange_loop.context.compacted"  # RFC-224

STRANGE_LOOP_STEP_STARTED = STRANGE_LOOP_STEP_STARTED
STRANGE_LOOP_STEP_QUEUED = STRANGE_LOOP_STEP_QUEUED
STRANGE_LOOP_STEP_COMPLETED = STRANGE_LOOP_STEP_COMPLETED
STRANGE_LOOP_PLAN_DECISION = STRANGE_LOOP_PLAN_DECISION
STRANGE_LOOP_PLAN_PHASE = STRANGE_LOOP_PLAN_PHASE
STRANGE_LOOP_REASONED = STRANGE_LOOP_REASONED
STRANGE_LOOP_CONTEXT_COMPACTED = STRANGE_LOOP_CONTEXT_COMPACTED

# Branch cognition (client UX)
BRANCH_CREATED = "soothe.cognition.branch.created"
BRANCH_RETRY_STARTED = "soothe.cognition.branch.retry.started"

# Autopilot system (client UX)
AUTOPILOT_STATUS_CHANGED = "soothe.system.autopilot.status.changed"
AUTOPILOT_GOAL_CREATED = "soothe.system.autopilot.goal.created"
AUTOPILOT_GOAL_PROGRESS = "soothe.system.autopilot.goal.reported"
AUTOPILOT_GOAL_COMPLETED = "soothe.system.autopilot.goal.completed"
AUTOPILOT_DREAMING_ENTERED = "soothe.system.autopilot.dreaming.started"
AUTOPILOT_DREAMING_EXITED = "soothe.system.autopilot.dreaming.completed"
AUTOPILOT_GOAL_SUSPENDED = "soothe.system.autopilot.goal.suspended"
AUTOPILOT_GOAL_BLOCKED = "soothe.system.autopilot.goal.blocked"

# Error
ERROR = "soothe.error.general.failed"

# LLM retry events (IG-504)
LLM_RETRY_ATTEMPT = "soothe.cognition.llm.retry.attempt"

__all__ = [
    "STRANGE_LOOP_COMPLETED",
    "STRANGE_LOOP_CONTEXT_COMPACTED",
    "STRANGE_LOOP_PLAN_DECISION",
    "STRANGE_LOOP_PLAN_PHASE",
    "STRANGE_LOOP_REASONED",
    "STRANGE_LOOP_STARTED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_STARTED",
    "AUTOPILOT_CHECKPOINT_SAVED",
    "AUTOPILOT_DREAMING_ENTERED",
    "AUTOPILOT_DREAMING_EXITED",
    "AUTOPILOT_GOAL_BLOCKED",
    "AUTOPILOT_GOAL_COMPLETED",
    "AUTOPILOT_GOAL_CREATED",
    "AUTOPILOT_GOAL_PROGRESS",
    "AUTOPILOT_GOAL_SUSPENDED",
    "AUTOPILOT_GOAL_VALIDATED",
    "AUTOPILOT_RELATIONSHIP_DETECTED",
    "AUTOPILOT_SEND_BACK",
    "AUTOPILOT_STATUS_CHANGED",
    "BRANCH_ANALYZED",
    "BRANCH_CREATED",
    "INTENT_CLASSIFIED",
    "BRANCH_PRUNED",
    "BRANCH_RETRY_STARTED",
    "CHECKPOINT_ANCHOR_CREATED",
    "CHECKPOINT_SAVED",
    "DAEMON_HEARTBEAT",
    "ERROR",
    "GOAL_BATCH_STARTED",
    "GOAL_COMPLETED",
    "GOAL_CREATED",
    "GOAL_DEFERRED",
    "GOAL_DIRECTIVES_APPLIED",
    "GOAL_FAILED",
    "GOAL_REPORT",
    "ITERATION_COMPLETED",
    "ITERATION_STARTED",
    "LLM_RETRY_ATTEMPT",
    "LOOP_COMPLETED",
    "LOOP_CREATED",
    "LOOP_DETACHED",
    "LOOP_REATTACHED",
    "LOOP_STARTED",
    "MCP_LIST_CHANGED",
    "MCP_TOOL_TIMEOUT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "PLAN_BATCH_STARTED",
    "PLAN_CREATED",
    "PLAN_DAG_SNAPSHOT",
    "PLAN_REFLECTED",
    "SKILL_BODY_LOADED",
    "PLUGIN_FAILED",
    "PLUGIN_LOADED",
    "PLUGIN_UNLOADED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "RECOVERY_RESUMED",
    "REPLAY_COMPLETE",
    "STRANGE_LOOP_COMPLETED",
    "STRANGE_LOOP_CONTEXT_COMPACTED",
    "STRANGE_LOOP_PLAN_DECISION",
    "STRANGE_LOOP_PLAN_PHASE",
    "STRANGE_LOOP_REASONED",
    "STRANGE_LOOP_STARTED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_STARTED",
]
