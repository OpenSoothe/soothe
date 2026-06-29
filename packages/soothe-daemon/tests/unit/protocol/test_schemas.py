"""Tests for Pydantic param models and PARAMS_REGISTRY (RFC-450 §6.2, IG-522 Phase 8).

Covers:
- Every params model validates correctly with valid input
- Field constraints (min_length, ge, etc.) reject invalid input
- PARAMS_REGISTRY covers all ~37 message types in both legacy flat and
  envelope (type, method) formats
- Extra fields are allowed (migration tolerance)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from soothe_daemon.protocol.schemas import (
    PARAMS_REGISTRY,
    # Auth
    AuthParams,
    AuthRefreshParams,
    AutopilotSubscribeParams,
    CommandParams,
    CommandRequestParams,
    ConfigGetParams,
    # Connection
    ConnectionInitParams,
    DaemonShutdownParams,
    # Daemon & config
    DaemonStatusParams,
    DisconnectParams,
    InvokeSkillParams,
    JobCancelParams,
    # Job RPC
    JobCreateParams,
    JobDagParams,
    JobGuidanceParams,
    JobPauseParams,
    JobResumeParams,
    JobStatusParams,
    LoopCardsFetchParams,
    LoopDeleteParams,
    LoopGetParams,
    LoopInputParams,
    LoopListParams,
    LoopMessagesParams,
    # Loop RPC
    LoopNewParams,
    LoopPruneParams,
    LoopReattachParams,
    LoopStateGetParams,
    LoopStateUpdateParams,
    LoopTreeParams,
    McpStatusParams,
    ModelsListParams,
    # Base
    SkillsListParams,
    # Subscription
    SubscribeParams,
)

# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


class TestParamsRegistryCompleteness:
    """PARAMS_REGISTRY must cover all ~37 message types."""

    # All legacy flat message types that the router dispatches.
    LEGACY_TYPES = {
        "connection_init",
        "ping",
        "pong",
        "command",
        "command_request",
        "detach",
        "daemon_ready",
        "auth",
        "auth_refresh",
        "loop_list",
        "loop_get",
        "loop_tree",
        "loop_prune",
        "loop_delete",
        "loop_new",
        "loop_reattach",
        "loop_subscribe",
        "loop_detach",
        "loop_input",
        "loop_messages",
        "loop_state_get",
        "loop_state_update",
        "loop_cards_fetch",
        "skills_list",
        "invoke_skill",
        "models_list",
        "mcp_status",
        "daemon_status",
        "daemon_shutdown",
        "config_get",
        "job_create",
        "job_status",
        "job_pause",
        "job_resume",
        "job_cancel",
        "job_dag",
        "job_guidance",
        "autopilot_subscribe",
        "autopilot_unsubscribe",
    }

    # All envelope (type, method) pairs per RFC-450 §9.2.
    ENVELOPE_ENTRIES = {
        ("request", "loop_list"),
        ("request", "loop_get"),
        ("request", "loop_tree"),
        ("request", "loop_prune"),
        ("request", "loop_delete"),
        ("request", "loop_new"),
        ("request", "loop_reattach"),
        ("request", "loop_input"),
        ("request", "loop_messages"),
        ("request", "loop_state_get"),
        ("request", "loop_state_update"),
        ("request", "loop_cards_fetch"),
        ("request", "loop_detach"),
        ("subscribe", "loop_events"),
        ("subscribe", "autopilot_events"),
        ("request", "job_create"),
        ("request", "job_status"),
        ("request", "job_pause"),
        ("request", "job_resume"),
        ("request", "job_cancel"),
        ("request", "job_dag"),
        ("request", "job_guidance"),
        ("request", "daemon_status"),
        ("request", "daemon_shutdown"),
        ("request", "config_get"),
        ("request", "skills_list"),
        ("request", "invoke_skill"),
        ("request", "models_list"),
        ("request", "mcp_status"),
        ("request", "auth"),
        ("request", "auth_refresh"),
        ("notification", "loop_input"),
        ("notification", "slash_command"),
        ("notification", "disconnect"),
        ("request", "rpc_command"),
        ("connection_init", None),
        ("ping", None),
        ("pong", None),
        ("unsubscribe", None),
    }

    def test_registry_has_control_type_entries(self) -> None:
        """The three non-envelope control types must have (type, None) entries."""
        for msg_type in ("connection_init", "ping", "pong"):
            assert (msg_type, None) in PARAMS_REGISTRY, (
                f"Missing PARAMS_REGISTRY entry for control type ({msg_type!r}, None)"
            )

    def test_registry_has_no_legacy_flat_entries(self) -> None:
        """Legacy flat-form (type, None) entries are removed (envelope-only)."""
        legacy = self.LEGACY_TYPES - {"connection_init", "ping", "pong"}
        for msg_type in legacy:
            assert (msg_type, None) not in PARAMS_REGISTRY, (
                f"Legacy flat entry ({msg_type!r}, None) should be removed"
            )

    def test_registry_has_all_envelope_entries(self) -> None:
        """Every envelope (type, method) pair must be registered."""
        for key in self.ENVELOPE_ENTRIES:
            assert key in PARAMS_REGISTRY, f"Missing PARAMS_REGISTRY entry for envelope key {key!r}"

    def test_registry_values_are_pydantic_models(self) -> None:
        """Every registry value must be a Pydantic BaseModel subclass."""
        from pydantic import BaseModel

        for key, model in PARAMS_REGISTRY.items():
            assert isinstance(model, type), f"{key}: {model!r} is not a class"
            assert issubclass(model, BaseModel), f"{key}: {model!r} is not a BaseModel"

    def test_registry_has_at_least_30_message_types(self) -> None:
        """The registry must cover all envelope (type, method) pairs + control types."""
        assert len(PARAMS_REGISTRY) >= 30, (
            f"PARAMS_REGISTRY has only {len(PARAMS_REGISTRY)} entries; expected >= 30"
        )

    def test_loop_input_registered_for_both_request_and_notification(self) -> None:
        """loop_input must be valid as both request and notification (RFC-450 §9.2)."""
        assert ("request", "loop_input") in PARAMS_REGISTRY
        assert ("notification", "loop_input") in PARAMS_REGISTRY


# ---------------------------------------------------------------------------
# Loop RPC param models
# ---------------------------------------------------------------------------


class TestLoopParams:
    """Validation tests for loop RPC param models."""

    def test_loop_get_valid(self) -> None:
        p = LoopGetParams.model_validate({"loop_id": "abc", "verbose": True, "tree": False})
        assert p.loop_id == "abc"
        assert p.verbose is True
        assert p.tree is False

    def test_loop_get_defaults(self) -> None:
        p = LoopGetParams.model_validate({"loop_id": "abc"})
        assert p.verbose is False
        assert p.tree is False

    def test_loop_get_missing_loop_id(self) -> None:
        with pytest.raises(ValidationError):
            LoopGetParams.model_validate({})

    def test_loop_get_empty_loop_id(self) -> None:
        with pytest.raises(ValidationError):
            LoopGetParams.model_validate({"loop_id": ""})

    def test_loop_list_valid(self) -> None:
        p = LoopListParams.model_validate({"status": "running", "limit": 10})
        assert p.status == "running"
        assert p.limit == 10

    def test_loop_list_defaults(self) -> None:
        p = LoopListParams.model_validate({})
        assert p.status is None
        assert p.limit is None

    def test_loop_tree_valid(self) -> None:
        p = LoopTreeParams.model_validate({"loop_id": "abc"})
        assert p.loop_id == "abc"

    def test_loop_tree_missing_loop_id(self) -> None:
        with pytest.raises(ValidationError):
            LoopTreeParams.model_validate({})

    def test_loop_prune_valid(self) -> None:
        p = LoopPruneParams.model_validate({"loop_id": "abc", "keep_latest": 3})
        assert p.keep_latest == 3

    def test_loop_prune_defaults(self) -> None:
        p = LoopPruneParams.model_validate({"loop_id": "abc"})
        assert p.keep_latest == 1

    def test_loop_delete_valid(self) -> None:
        p = LoopDeleteParams.model_validate({"loop_id": "abc"})
        assert p.loop_id == "abc"

    def test_loop_new_valid(self) -> None:
        p = LoopNewParams.model_validate(
            {
                "workspace": "/tmp",
                "user_id": "user1",
                "is_ephemeral": True,
            }
        )
        assert p.workspace == "/tmp"
        assert p.user_id == "user1"
        assert p.is_ephemeral is True

    def test_loop_new_defaults(self) -> None:
        p = LoopNewParams.model_validate({})
        assert p.workspace is None
        assert p.is_ephemeral is False

    def test_loop_reattach_valid(self) -> None:
        p = LoopReattachParams.model_validate({"loop_id": "abc"})
        assert p.loop_id == "abc"

    def test_loop_input_string_content(self) -> None:
        p = LoopInputParams.model_validate({"loop_id": "abc", "content": "hello"})
        assert p.loop_id == "abc"
        assert p.content == "hello"

    def test_loop_input_dict_content(self) -> None:
        p = LoopInputParams.model_validate({"loop_id": "abc", "content": {"text": "hi"}})
        assert isinstance(p.content, dict)

    def test_loop_input_missing_content(self) -> None:
        with pytest.raises(ValidationError):
            LoopInputParams.model_validate({"loop_id": "abc"})

    def test_loop_input_optional_fields(self) -> None:
        p = LoopInputParams.model_validate(
            {
                "loop_id": "abc",
                "content": "hi",
                "autonomous": True,
                "max_iterations": 5,
                "preferred_subagent": "researcher",
                "model": "openai:gpt-4",
                "intent_hint": "code",
                "clarification_mode": "manual",
                "clarification_answer": True,
            }
        )
        assert p.autonomous is True
        assert p.max_iterations == 5
        assert p.preferred_subagent == "researcher"

    def test_loop_messages_valid(self) -> None:
        p = LoopMessagesParams.model_validate({"loop_id": "abc", "limit": 50, "offset": 10})
        assert p.limit == 50
        assert p.offset == 10

    def test_loop_messages_defaults(self) -> None:
        p = LoopMessagesParams.model_validate({"loop_id": "abc"})
        assert p.limit == 100
        assert p.offset == 0

    def test_loop_state_get_valid(self) -> None:
        p = LoopStateGetParams.model_validate({"loop_id": "abc", "keys": ["k1", "k2"]})
        assert p.keys == ["k1", "k2"]

    def test_loop_state_get_defaults(self) -> None:
        p = LoopStateGetParams.model_validate({"loop_id": "abc"})
        assert p.keys is None

    def test_loop_state_update_valid(self) -> None:
        p = LoopStateUpdateParams.model_validate(
            {
                "loop_id": "abc",
                "values": {"key": "value"},
            }
        )
        assert p.values == {"key": "value"}

    def test_loop_state_update_missing_values(self) -> None:
        with pytest.raises(ValidationError):
            LoopStateUpdateParams.model_validate({"loop_id": "abc"})

    def test_loop_cards_fetch_valid(self) -> None:
        p = LoopCardsFetchParams.model_validate({"loop_id": "abc", "since": "2024-01-01"})
        assert p.since == "2024-01-01"

    def test_loop_cards_fetch_defaults(self) -> None:
        p = LoopCardsFetchParams.model_validate({"loop_id": "abc"})
        assert p.since is None


# ---------------------------------------------------------------------------
# Subscription param models
# ---------------------------------------------------------------------------


class TestSubscriptionParams:
    """Validation tests for subscription param models."""

    def test_subscribe_valid(self) -> None:
        p = SubscribeParams.model_validate(
            {
                "loop_id": "abc",
                "stream_delivery": "batch",
                "wire_tier": "compact",
            }
        )
        assert p.stream_delivery == "batch"
        assert p.wire_tier == "compact"

    def test_subscribe_defaults(self) -> None:
        p = SubscribeParams.model_validate({"loop_id": "abc"})
        assert p.stream_delivery == "adaptive"
        assert p.wire_tier == "full"

    def test_subscribe_invalid_stream_delivery(self) -> None:
        with pytest.raises(ValidationError):
            SubscribeParams.model_validate({"loop_id": "abc", "stream_delivery": "invalid"})

    def test_subscribe_invalid_wire_tier(self) -> None:
        with pytest.raises(ValidationError):
            SubscribeParams.model_validate({"loop_id": "abc", "wire_tier": "mega"})

    def test_autopilot_subscribe_valid(self) -> None:
        p = AutopilotSubscribeParams.model_validate({})
        assert p is not None


# ---------------------------------------------------------------------------
# Job RPC param models
# ---------------------------------------------------------------------------


class TestJobParams:
    """Validation tests for job RPC param models."""

    def test_job_create_valid(self) -> None:
        p = JobCreateParams.model_validate(
            {
                "goal": "build feature",
                "workspace": "/tmp",
                "autonomous": True,
            }
        )
        assert p.goal == "build feature"
        assert p.autonomous is True

    def test_job_create_missing_goal(self) -> None:
        with pytest.raises(ValidationError):
            JobCreateParams.model_validate({})

    def test_job_create_empty_goal(self) -> None:
        with pytest.raises(ValidationError):
            JobCreateParams.model_validate({"goal": ""})

    def test_job_status_valid(self) -> None:
        p = JobStatusParams.model_validate({"job_id": "job-1"})
        assert p.job_id == "job-1"

    def test_job_status_missing_job_id(self) -> None:
        with pytest.raises(ValidationError):
            JobStatusParams.model_validate({})

    def test_job_pause_valid(self) -> None:
        JobPauseParams.model_validate({"job_id": "job-1"})

    def test_job_resume_valid(self) -> None:
        JobResumeParams.model_validate({"job_id": "job-1"})

    def test_job_cancel_valid(self) -> None:
        JobCancelParams.model_validate({"job_id": "job-1"})

    def test_job_dag_valid(self) -> None:
        JobDagParams.model_validate({"job_id": "job-1"})

    def test_job_guidance_with_content(self) -> None:
        p = JobGuidanceParams.model_validate({"job_id": "job-1", "content": "focus"})
        assert p.content == "focus"

    def test_job_guidance_missing_content(self) -> None:
        with pytest.raises(ValidationError):
            JobGuidanceParams.model_validate({"job_id": "job-1"})

    def test_job_guidance_missing_job_id(self) -> None:
        with pytest.raises(ValidationError):
            JobGuidanceParams.model_validate({"content": "focus"})


# ---------------------------------------------------------------------------
# Daemon & config param models
# ---------------------------------------------------------------------------


class TestDaemonConfigParams:
    """Validation tests for daemon/config param models."""

    def test_daemon_status_valid(self) -> None:
        DaemonStatusParams.model_validate({})

    def test_daemon_shutdown_valid(self) -> None:
        DaemonShutdownParams.model_validate({})

    def test_config_get_valid(self) -> None:
        p = ConfigGetParams.model_validate({"section": "agent"})
        assert p.section == "agent"

    def test_config_get_defaults(self) -> None:
        p = ConfigGetParams.model_validate({})
        assert p.section is None


# ---------------------------------------------------------------------------
# Skills & models param models
# ---------------------------------------------------------------------------


class TestSkillsModelsParams:
    """Validation tests for skills/models param models."""

    def test_skills_list_valid(self) -> None:
        SkillsListParams.model_validate({})

    def test_models_list_valid(self) -> None:
        ModelsListParams.model_validate({})

    def test_invoke_skill_valid(self) -> None:
        p = InvokeSkillParams.model_validate({"skill": "my-skill", "args": "test"})
        assert p.skill == "my-skill"
        assert p.args == "test"

    def test_invoke_skill_defaults(self) -> None:
        p = InvokeSkillParams.model_validate({"skill": "my-skill"})
        assert p.args == ""

    def test_invoke_skill_missing_skill(self) -> None:
        with pytest.raises(ValidationError):
            InvokeSkillParams.model_validate({})

    def test_invoke_skill_empty_skill(self) -> None:
        with pytest.raises(ValidationError):
            InvokeSkillParams.model_validate({"skill": ""})

    def test_mcp_status_valid(self) -> None:
        McpStatusParams.model_validate({})


# ---------------------------------------------------------------------------
# Auth param models
# ---------------------------------------------------------------------------


class TestAuthParams:
    """Validation tests for auth param models."""

    def test_auth_valid(self) -> None:
        p = AuthParams.model_validate({"access_key": "ak", "secret_key": "sk"})
        assert p.access_key == "ak"
        assert p.secret_key == "sk"

    def test_auth_defaults(self) -> None:
        p = AuthParams.model_validate({})
        assert p.access_key == ""
        assert p.secret_key == ""

    def test_auth_refresh_valid(self) -> None:
        p = AuthRefreshParams.model_validate({"refresh_token": "rt"})
        assert p.refresh_token == "rt"

    def test_auth_refresh_defaults(self) -> None:
        p = AuthRefreshParams.model_validate({})
        assert p.refresh_token == ""


# ---------------------------------------------------------------------------
# Command param models
# ---------------------------------------------------------------------------


class TestCommandParams:
    """Validation tests for command param models."""

    def test_slash_command_valid(self) -> None:
        p = CommandParams.model_validate({"cmd": "/exit"})
        assert p.cmd == "/exit"

    def test_slash_command_missing_cmd(self) -> None:
        with pytest.raises(ValidationError):
            CommandParams.model_validate({})

    def test_slash_command_empty_cmd(self) -> None:
        with pytest.raises(ValidationError):
            CommandParams.model_validate({"cmd": ""})

    def test_rpc_command_valid(self) -> None:
        p = CommandRequestParams.model_validate({"command": "autopilot_status", "payload": {}})
        assert p.command == "autopilot_status"

    def test_rpc_command_with_payload(self) -> None:
        p = CommandRequestParams.model_validate(
            {
                "command": "cron_add",
                "payload": {"name": "test"},
            }
        )
        assert p.payload == {"name": "test"}

    def test_rpc_command_missing_command(self) -> None:
        # CommandRequestParams is intentionally permissive (no required fields)
        # so the handler can return a domain-specific error for missing command.
        p = CommandRequestParams.model_validate({})
        assert p is not None


# ---------------------------------------------------------------------------
# Connection param models
# ---------------------------------------------------------------------------


class TestConnectionParams:
    """Validation tests for connection param models."""

    def test_connection_init_valid(self) -> None:
        p = ConnectionInitParams.model_validate(
            {
                "client_version": "0.5.0",
                "accept_proto": ["1"],
                "capabilities": ["streaming"],
            }
        )
        assert p.client_version == "0.5.0"
        assert p.accept_proto == ["1"]
        assert p.capabilities == ["streaming"]

    def test_connection_init_defaults(self) -> None:
        p = ConnectionInitParams.model_validate({"client_version": "0.5.0"})
        assert p.client_name is None
        assert p.accept_proto is None
        assert p.capabilities is None

    def test_disconnect_valid(self) -> None:
        DisconnectParams.model_validate({})


# ---------------------------------------------------------------------------
# Extra fields tolerance (migration)
# ---------------------------------------------------------------------------


class TestExtraFieldsTolerance:
    """All models must tolerate extra fields (migration window)."""

    def test_loop_get_accepts_extra_fields(self) -> None:
        """Extra fields like 'type', 'request_id' must not cause errors."""
        p = LoopGetParams.model_validate(
            {
                "loop_id": "abc",
                "type": "loop_get",
                "request_id": "r1",
                "proto": "1",
            }
        )
        assert p.loop_id == "abc"

    def test_loop_input_accepts_envelope_keys(self) -> None:
        p = LoopInputParams.model_validate(
            {
                "loop_id": "abc",
                "content": "hi",
                "type": "notification",
                "method": "loop_input",
                "proto": "1",
            }
        )
        assert p.loop_id == "abc"
