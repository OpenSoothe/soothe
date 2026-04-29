"""Centralized event type string constants for Soothe system.

This module provides the SINGLE SOURCE OF TRUTH for all event type string constants.
Import from this module instead of hardcoding strings or importing from event_catalog.

Architecture:
- This file: Event type string constants ONLY
- event_catalog.py: Event models, registry, registration logic

RFC-0015: 4-segment naming convention: soothe.<domain>.<component>.<action>

Usage:
    from soothe.core.events import GOAL_CREATED, BRANCH_CREATED

    # For comparisons, routing, event emission
    if event_type == GOAL_CREATED:
        ...
"""

from __future__ import annotations

# ============================================================================
# LIFECYCLE DOMAIN (soothe.lifecycle.*)
# ============================================================================

# Thread lifecycle (internal)
THREAD_CREATED = "soothe.lifecycle.thread.started"
THREAD_STARTED = "soothe.lifecycle.thread.started"
THREAD_RESUMED = "soothe.lifecycle.thread.resumed"
THREAD_SAVED = "soothe.lifecycle.thread.saved"
THREAD_ENDED = "soothe.lifecycle.thread.ended"
THREAD_SWITCHED = "soothe.lifecycle.thread.switched"

# Iteration lifecycle
ITERATION_STARTED = "soothe.lifecycle.iteration.started"
ITERATION_COMPLETED = "soothe.lifecycle.iteration.completed"

# Checkpoint lifecycle
CHECKPOINT_SAVED = "soothe.lifecycle.checkpoint.saved"
CHECKPOINT_ANCHOR_CREATED = "soothe.lifecycle.checkpoint.anchor.created"

# Recovery lifecycle
RECOVERY_RESUMED = "soothe.lifecycle.recovery.resumed"

# Loop lifecycle (NEW)
LOOP_CREATED = "soothe.lifecycle.loop.created"
LOOP_STARTED = "soothe.lifecycle.loop.started"
LOOP_DETACHED = "soothe.lifecycle.loop.detached"
LOOP_REATTACHED = "soothe.lifecycle.loop.reattached"
LOOP_COMPLETED = "soothe.lifecycle.loop.completed"
HISTORY_REPLAY_COMPLETE = "soothe.lifecycle.loop.history.replayed"

# ============================================================================
# COGNITION DOMAIN (soothe.cognition.*)
# ============================================================================

# Goal cognition
GOAL_CREATED = "soothe.cognition.goal.created"
GOAL_COMPLETED = "soothe.cognition.goal.completed"
GOAL_FAILED = "soothe.cognition.goal.failed"
GOAL_BATCH_STARTED = "soothe.cognition.goal.batch.started"
GOAL_REPORT = "soothe.cognition.goal.reported"
GOAL_DIRECTIVES_APPLIED = "soothe.cognition.goal.directives.applied"
GOAL_DEFERRED = "soothe.cognition.goal.deferred"

# Plan cognition
PLAN_CREATED = "soothe.cognition.plan.created"
PLAN_STEP_STARTED = "soothe.cognition.plan.step.started"
PLAN_STEP_COMPLETED = "soothe.cognition.plan.step.completed"
PLAN_STEP_FAILED = "soothe.cognition.plan.step.failed"
PLAN_BATCH_STARTED = "soothe.cognition.plan.batch.started"
PLAN_REFLECTED = "soothe.cognition.plan.reflected"
PLAN_DAG_SNAPSHOT = "soothe.cognition.plan.dag_snapshot"

# AgentLoop cognition
AGENT_LOOP_STARTED = "soothe.cognition.agent_loop.started"
AGENT_LOOP_COMPLETED = "soothe.cognition.agent_loop.completed"
AGENT_LOOP_STEP_STARTED = "soothe.cognition.agent_loop.step.started"
AGENT_LOOP_STEP_COMPLETED = "soothe.cognition.agent_loop.step.completed"

# Branch cognition (NEW)
BRANCH_CREATED = "soothe.cognition.branch.created"
BRANCH_ANALYZED = "soothe.cognition.branch.analyzed"
BRANCH_RETRY_STARTED = "soothe.cognition.branch.retry.started"
BRANCH_PRUNED = "soothe.cognition.branch.pruned"

# ============================================================================
# PROTOCOL DOMAIN (soothe.protocol.*)
# ============================================================================

# Memory protocol
MEMORY_RECALLED = "soothe.protocol.memory.recalled"
MEMORY_STORED = "soothe.protocol.memory.stored"

# Policy protocol
POLICY_CHECKED = "soothe.protocol.policy.checked"
POLICY_DENIED = "soothe.protocol.policy.denied"

# ============================================================================
# SYSTEM DOMAIN (soothe.system.*)
# ============================================================================

DAEMON_HEARTBEAT = "soothe.system.daemon.heartbeat"

# Autopilot system
AUTOPILLOT_STATUS_CHANGED = "soothe.system.autopilot.status.changed"
AUTOPILLOT_GOAL_CREATED = "soothe.system.autopilot.goal.created"
AUTOPILLOT_GOAL_PROGRESS = "soothe.system.autopilot.goal.reported"
AUTOPILLOT_GOAL_COMPLETED = "soothe.system.autopilot.goal.completed"
AUTOPILLOT_DREAMING_ENTERED = "soothe.system.autopilot.dreaming.started"
AUTOPILLOT_DREAMING_EXITED = "soothe.system.autopilot.dreaming.completed"
AUTOPILLOT_GOAL_VALIDATED = "soothe.system.autopilot.goal.validated"
AUTOPILLOT_GOAL_SUSPENDED = "soothe.system.autopilot.goal.suspended"
AUTOPILLOT_SEND_BACK = "soothe.system.autopilot.feedback.sent"
AUTOPILLOT_RELATIONSHIP_DETECTED = "soothe.system.autopilot.relationship.detected"
AUTOPILLOT_CHECKPOINT_SAVED = "soothe.system.autopilot.checkpoint.saved"
AUTOPILLOT_GOAL_BLOCKED = "soothe.system.autopilot.goal.blocked"

# ============================================================================
# PLUGIN DOMAIN (soothe.plugin.*)
# ============================================================================

PLUGIN_LOADED = "soothe.plugin.loaded"
PLUGIN_FAILED = "soothe.plugin.failed"
PLUGIN_UNLOADED = "soothe.plugin.unloaded"

# ============================================================================
# ERROR DOMAIN (soothe.error.*)
# ============================================================================

ERROR = "soothe.error.general.failed"


__all__ = [
    # Lifecycle - Thread
    "THREAD_CREATED",
    "THREAD_STARTED",
    "THREAD_RESUMED",
    "THREAD_SAVED",
    "THREAD_ENDED",
    "THREAD_SWITCHED",
    # Lifecycle - Iteration
    "ITERATION_STARTED",
    "ITERATION_COMPLETED",
    # Lifecycle - Checkpoint
    "CHECKPOINT_SAVED",
    "CHECKPOINT_ANCHOR_CREATED",
    # Lifecycle - Recovery
    "RECOVERY_RESUMED",
    # Lifecycle - Loop
    "LOOP_CREATED",
    "LOOP_STARTED",
    "LOOP_DETACHED",
    "LOOP_REATTACHED",
    "LOOP_COMPLETED",
    "HISTORY_REPLAY_COMPLETE",
    # Cognition - Goal
    "GOAL_CREATED",
    "GOAL_COMPLETED",
    "GOAL_FAILED",
    "GOAL_BATCH_STARTED",
    "GOAL_REPORT",
    "GOAL_DIRECTIVES_APPLIED",
    "GOAL_DEFERRED",
    # Cognition - Plan
    "PLAN_CREATED",
    "PLAN_STEP_STARTED",
    "PLAN_STEP_COMPLETED",
    "PLAN_STEP_FAILED",
    "PLAN_BATCH_STARTED",
    "PLAN_REFLECTED",
    "PLAN_DAG_SNAPSHOT",
    # Cognition - AgentLoop
    "AGENT_LOOP_STARTED",
    "AGENT_LOOP_COMPLETED",
    "AGENT_LOOP_STEP_STARTED",
    "AGENT_LOOP_STEP_COMPLETED",
    # Cognition - Branch
    "BRANCH_CREATED",
    "BRANCH_ANALYZED",
    "BRANCH_RETRY_STARTED",
    "BRANCH_PRUNED",
    # Protocol - Memory
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    # Protocol - Policy
    "POLICY_CHECKED",
    "POLICY_DENIED",
    # System - Daemon
    "DAEMON_HEARTBEAT",
    # System - Autopilot
    "AUTOPILLOT_STATUS_CHANGED",
    "AUTOPILLOT_GOAL_CREATED",
    "AUTOPILLOT_GOAL_PROGRESS",
    "AUTOPILLOT_GOAL_COMPLETED",
    "AUTOPILLOT_DREAMING_ENTERED",
    "AUTOPILLOT_DREAMING_EXITED",
    "AUTOPILLOT_GOAL_VALIDATED",
    "AUTOPILLOT_GOAL_SUSPENDED",
    "AUTOPILLOT_SEND_BACK",
    "AUTOPILLOT_RELATIONSHIP_DETECTED",
    "AUTOPILLOT_CHECKPOINT_SAVED",
    "AUTOPILLOT_GOAL_BLOCKED",
    # Plugin
    "PLUGIN_LOADED",
    "PLUGIN_FAILED",
    "PLUGIN_UNLOADED",
    # Error
    "ERROR",
]
