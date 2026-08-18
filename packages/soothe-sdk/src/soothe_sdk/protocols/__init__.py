"""Protocol definitions for Soothe plugin authors.

These runtime-agnostic protocols define the stable interfaces that
community plugins can depend on without requiring the full host runtime.
"""

from soothe_sdk.protocols.concurrency import ConcurrencyPolicy
from soothe_sdk.protocols.core_agent import CoreAgentCapabilities, CoreAgentProtocol
from soothe_sdk.protocols.durability import (
    DurabilityProtocol,
    ThreadFilter,
    ThreadInfo,
    ThreadMetadata,
)
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
from soothe_sdk.protocols.memory import MemoryItem, MemoryProtocol
from soothe_sdk.protocols.operation_security import (
    OperationKind,
    OperationSecurityContext,
    OperationSecurityDecision,
    OperationSecurityProtocol,
    OperationSecurityRequest,
)
from soothe_sdk.protocols.persistence import AsyncPersistStore
from soothe_sdk.protocols.planner import (
    GoalDirective,
    GoalReport,
    Plan,
    PlanContext,
    PlannerProtocol,
    PlanStep,
    Reflection,
    StepReport,
    StepResult,
    planner_outcome_text_preview,
)
from soothe_sdk.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
    PolicyProtocol,
)
from soothe_sdk.protocols.vector_store import VectorRecord, VectorStoreProtocol

__all__ = [
    # CoreAgent
    "CoreAgentCapabilities",
    "CoreAgentProtocol",
    # Persistence
    "AsyncPersistStore",
    # Policy
    "Permission",
    "PermissionSet",
    "ActionRequest",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyProtocol",
    # Identity
    "User",
    "AKSKPair",
    "TokenClaims",
    "ExternalIdentityMapping",
    "AuthResult",
    "TokenRefreshResult",
    "TokenInfo",
    "IdentityStatus",
    "IdentityProtocol",
    # Vector store
    "VectorRecord",
    "VectorStoreProtocol",
    # Concurrency / planner
    "ConcurrencyPolicy",
    "GoalDirective",
    "GoalReport",
    "Plan",
    "PlanContext",
    "PlanStep",
    "PlannerProtocol",
    "Reflection",
    "StepReport",
    "StepResult",
    "planner_outcome_text_preview",
    # Memory
    "MemoryItem",
    "MemoryProtocol",
    # Durability
    "DurabilityProtocol",
    "ThreadFilter",
    "ThreadInfo",
    "ThreadMetadata",
    # Operation security
    "OperationKind",
    "OperationSecurityContext",
    "OperationSecurityDecision",
    "OperationSecurityProtocol",
    "OperationSecurityRequest",
]
