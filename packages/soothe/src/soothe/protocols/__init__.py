"""Soothe protocol definitions -- runtime-agnostic interfaces."""

# Identity protocol (RFC-307) - re-exported from soothe-sdk
from soothe_sdk.protocols.identity import (
    AKSKPair,
    AuthResult,
    ExternalIdentityMapping,
    IdentityProtocol,
    IdentityStatus,
    TokenClaims,
    TokenInfo,
    TokenRefreshResult,
    User,
)

from soothe.protocols.concurrency import ConcurrencyPolicy
from soothe.protocols.core_agent import CoreAgentProtocol
from soothe.protocols.durability import (
    DurabilityProtocol,
    ThreadFilter,
    ThreadInfo,
    ThreadMetadata,
)
from soothe.protocols.loop_planner import LoopPlannerProtocol
from soothe.protocols.loop_working_memory import LoopWorkingMemoryProtocol
from soothe.protocols.memory import MemoryItem, MemoryProtocol
from soothe.protocols.operation_security import (
    OperationKind,
    OperationSecurityContext,
    OperationSecurityDecision,
    OperationSecurityProtocol,
    OperationSecurityRequest,
)
from soothe.protocols.persistence import AsyncPersistStore
from soothe.protocols.planner import (
    GoalReport,
    Plan,
    PlanContext,
    PlannerProtocol,
    PlanStep,
    Reflection,
    StepReport,
    StepResult,
)
from soothe.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
    PolicyProtocol,
)
from soothe.protocols.runner import LoopRunnerProtocol, LoopRunRequest
from soothe.protocols.vector_store import VectorRecord, VectorStoreProtocol

__all__ = [
    "ActionRequest",
    "AsyncPersistStore",
    "ConcurrencyPolicy",
    "CoreAgentProtocol",
    "DurabilityProtocol",
    "GoalReport",
    "LoopPlannerProtocol",
    "LoopRunRequest",
    "LoopRunnerProtocol",
    "LoopWorkingMemoryProtocol",
    "MemoryItem",
    "MemoryProtocol",
    "OperationKind",
    "OperationSecurityContext",
    "OperationSecurityDecision",
    "OperationSecurityProtocol",
    "OperationSecurityRequest",
    "Permission",
    "PermissionSet",
    "Plan",
    "PlanContext",
    "PlanStep",
    "PlannerProtocol",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyProtocol",
    "Reflection",
    "StepReport",
    "StepResult",
    "ThreadFilter",
    "ThreadInfo",
    "ThreadMetadata",
    "VectorRecord",
    "VectorStoreProtocol",
    # Identity (RFC-307)
    "User",
    "AKSKPair",
    "TokenClaims",
    "ExternalIdentityMapping",
    "AuthResult",
    "TokenRefreshResult",
    "TokenInfo",
    "IdentityStatus",
    "IdentityProtocol",
]
