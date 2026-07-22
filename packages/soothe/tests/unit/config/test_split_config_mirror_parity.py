"""IG-706: identity guards for nano-owned config models re-exported by host.

Shared schema classes must be the same class object on both sides
(``soothe.config.models.X is soothe_nano.config.models.X``).
"""

from __future__ import annotations

import pytest

# Re-exported nano-owned models (must stay identical class objects).
_REEXPORTED_MODELS = (
    "AgentRuntimeConfig",
    "CodeInterpreterConfig",
    "ConsoleLoggingConfig",
    "CoreAgentMiddlewareConfig",
    "DeepxivToolsConfig",
    "DurabilityProtocolConfig",
    "EmbeddingProfile",
    "ExecutionToolsConfig",
    "FailureIntentConfig",
    "FileLoggingConfig",
    "FilesystemMiddlewareConfig",
    "GlobalHistoryConfig",
    "HttpRequestsToolsConfig",
    "LLMRateLimitConfig",
    "LangfuseIntegrationConfig",
    "LoopToolOutputConfig",
    "MCPAuthHeaders",
    "MCPServerConfig",
    "MCPTransport",
    "MemUConfig",
    "ModelProviderConfig",
    "ModelRouter",
    "ObservabilityConfig",
    "OptimizationConfig",
    "PersistenceConfig",
    "PlannerProtocolConfig",
    "PluginConfig",
    "PolicyProtocolConfig",
    "ProgressiveMCPConfig",
    "ProgressiveSkillsConfig",
    "ProgressiveToolsConfig",
    "ProtocolsConfig",
    "ReportOutputConfig",
    "RoleRoutingConfig",
    "RouterProfile",
    "SecurityConfig",
    "StructuredPlanConfig",
    "SubagentConfig",
    "ThreadLoggingConfig",
    "ToolCallLimitConfig",
    "ToolConfig",
    "ToolRetryConfig",
    "ToolTimeoutConfig",
    "ToolsConfig",
    "UIConfig",
    "UpdateConfig",
    "VectorStoreProviderConfig",
    "VectorStoreRouter",
    "WebSearchConfig",
    "WorkspaceMountConfig",
)


@pytest.mark.parametrize("name", _REEXPORTED_MODELS)
def test_reexported_config_model_is_nano_class(name: str) -> None:
    import soothe_nano.config.models as nano_models

    import soothe.config.models as host_models

    host_cls = getattr(host_models, name, None)
    nano_cls = getattr(nano_models, name, None)
    assert host_cls is not None, f"{name} missing from soothe.config.models"
    assert nano_cls is not None, f"{name} missing from soothe_nano.config.models"
    assert host_cls is nano_cls, f"{name} must be re-exported (same class object)"


def test_host_agent_config_subclasses_nano() -> None:
    import soothe_nano.config.models as nano_models

    import soothe.config.models as host_models

    assert issubclass(host_models.AgentConfig, nano_models.AgentConfig)
    assert host_models.AgentConfig is not nano_models.AgentConfig
    host_only = set(host_models.AgentConfig.model_fields) - set(
        nano_models.AgentConfig.model_fields
    )
    assert host_only == {
        "autopilot",
        "clarification",
        "final_response",
        "goal_completion_mode",
        "loop",
        "veritas",
    }
