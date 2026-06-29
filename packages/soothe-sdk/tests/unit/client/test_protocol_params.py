"""Unit tests for client-side params validation models (RFC-450 §6.5).

These models mirror the daemon's PARAMS_REGISTRY and allow clients to validate
params before sending, catching errors early and reducing daemon-side error
round-trips.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from soothe_sdk.client.protocol_params import (
    AuthParams,
    AutopilotSubscribeParams,
    ConfigGetParams,
    DaemonStatusParams,
    DisconnectParams,
    InvokeSkillParams,
    JobCancelParams,
    JobCreateParams,
    JobDagParams,
    JobGuidanceParams,
    JobPauseParams,
    JobResumeParams,
    JobStatusParams,
    LoopCardsFetchParams,
    LoopDeleteParams,
    LoopDetachParams,
    LoopGetParams,
    LoopInputParams,
    LoopListParams,
    LoopMessagesParams,
    LoopNewParams,
    LoopPruneParams,
    LoopReattachParams,
    LoopStateGetParams,
    LoopStateUpdateParams,
    LoopTreeParams,
    McpStatusParams,
    ModelsListParams,
    RpcCommandParams,
    SkillsListParams,
    SlashCommandParams,
    SubscribeParams,
)

# ---------------------------------------------------------------------------
# Loop RPC params
# ---------------------------------------------------------------------------


class TestLoopGetParams:
    """LoopGetParams validation."""

    def test_valid_with_required_loop_id(self) -> None:
        params = LoopGetParams(loop_id="abc123")
        assert params.loop_id == "abc123"
        assert params.verbose is False
        assert params.tree is False

    def test_valid_with_all_fields(self) -> None:
        params = LoopGetParams(loop_id="abc", verbose=True, tree=True)
        assert params.verbose is True
        assert params.tree is True

    def test_missing_loop_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            LoopGetParams()  # type: ignore[call-arg]

    def test_empty_loop_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            LoopGetParams(loop_id="")


class TestLoopListParams:
    """LoopListParams validation."""

    def test_empty_params_valid(self) -> None:
        params = LoopListParams()
        assert params.status is None
        assert params.limit is None

    def test_with_status_and_limit(self) -> None:
        params = LoopListParams(status="running", limit=10)
        assert params.status == "running"
        assert params.limit == 10

    def test_zero_limit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoopListParams(limit=0)


class TestLoopInputParams:
    """LoopInputParams validation — the primary user-input method."""

    def test_valid_string_content(self) -> None:
        params = LoopInputParams(loop_id="abc", content="Hello")
        assert params.content == "Hello"
        assert params.autonomous is False

    def test_valid_dict_content(self) -> None:
        params = LoopInputParams(loop_id="abc", content={"text": "Hi"})
        assert params.content == {"text": "Hi"}

    def test_missing_content_raises(self) -> None:
        with pytest.raises(ValidationError):
            LoopInputParams(loop_id="abc")  # type: ignore[call-arg]

    def test_empty_loop_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            LoopInputParams(loop_id="", content="Hi")

    def test_clarification_mode_pattern(self) -> None:
        params = LoopInputParams(loop_id="abc", content="Hi", clarification_mode="manual")
        assert params.clarification_mode == "manual"

    def test_clarification_mode_invalid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoopInputParams(loop_id="abc", content="Hi", clarification_mode="bogus")


class TestLoopNewParams:
    """LoopNewParams validation."""

    def test_empty_params_valid(self) -> None:
        params = LoopNewParams()
        assert params.is_ephemeral is False
        assert params.workspace is None

    def test_with_workspace_and_user(self) -> None:
        params = LoopNewParams(workspace="/tmp", user_id="alice", is_ephemeral=True)
        assert params.workspace == "/tmp"
        assert params.user_id == "alice"
        assert params.is_ephemeral is True


class TestLoopStateUpdateParams:
    """LoopStateUpdateParams validation."""

    def test_valid_with_values(self) -> None:
        params = LoopStateUpdateParams(loop_id="abc", values={"key": "val"})
        assert params.values == {"key": "val"}

    def test_missing_values_raises(self) -> None:
        with pytest.raises(ValidationError):
            LoopStateUpdateParams(loop_id="abc")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Subscription params
# ---------------------------------------------------------------------------


class TestSubscribeParams:
    """SubscribeParams validation for loop_events."""

    def test_valid_defaults(self) -> None:
        params = SubscribeParams(loop_id="abc")
        assert params.stream_delivery == "adaptive"
        assert params.wire_tier == "full"

    def test_invalid_stream_delivery_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubscribeParams(loop_id="abc", stream_delivery="bogus")  # type: ignore[arg-type]

    def test_invalid_wire_tier_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubscribeParams(loop_id="abc", wire_tier="bogus")  # type: ignore[arg-type]


class TestAutopilotSubscribeParams:
    """AutopilotSubscribeParams validation."""

    def test_empty_params_valid(self) -> None:
        params = AutopilotSubscribeParams()
        assert params.job_id is None

    def test_with_job_id(self) -> None:
        params = AutopilotSubscribeParams(job_id="job1")
        assert params.job_id == "job1"


# ---------------------------------------------------------------------------
# Job RPC params
# ---------------------------------------------------------------------------


class TestJobCreateParams:
    """JobCreateParams validation."""

    def test_valid_with_goal(self) -> None:
        params = JobCreateParams(goal="Build feature X")
        assert params.goal == "Build feature X"
        assert params.autonomous is False

    def test_missing_goal_raises(self) -> None:
        with pytest.raises(ValidationError):
            JobCreateParams()  # type: ignore[call-arg]

    def test_empty_goal_raises(self) -> None:
        with pytest.raises(ValidationError):
            JobCreateParams(goal="")


class TestJobGuidanceParams:
    """JobGuidanceParams validation — content is the canonical field."""

    def test_content_required(self) -> None:
        with pytest.raises(ValidationError):
            JobGuidanceParams(job_id="job1")  # type: ignore[call-arg]

    def test_content_canonical(self) -> None:
        params = JobGuidanceParams(job_id="job1", content="Do X")
        assert params.content == "Do X"

    def test_missing_job_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            JobGuidanceParams(content="Do X")  # type: ignore[call-arg]


class TestJobIdParams:
    """Common job_id params (status/pause/resume/cancel/dag)."""

    @pytest.mark.parametrize(
        "model_cls",
        [JobStatusParams, JobPauseParams, JobResumeParams, JobCancelParams, JobDagParams],
    )
    def test_requires_job_id(self, model_cls: type) -> None:
        with pytest.raises(ValidationError):
            model_cls()  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "model_cls",
        [JobStatusParams, JobPauseParams, JobResumeParams, JobCancelParams, JobDagParams],
    )
    def test_empty_job_id_rejected(self, model_cls: type) -> None:
        with pytest.raises(ValidationError):
            model_cls(job_id="")

    @pytest.mark.parametrize(
        "model_cls",
        [JobStatusParams, JobPauseParams, JobResumeParams, JobCancelParams, JobDagParams],
    )
    def test_valid_job_id(self, model_cls: type) -> None:
        params = model_cls(job_id="job1")
        assert params.job_id == "job1"


# ---------------------------------------------------------------------------
# Skills & models params
# ---------------------------------------------------------------------------


class TestInvokeSkillParams:
    """InvokeSkillParams validation."""

    def test_valid_with_skill(self) -> None:
        params = InvokeSkillParams(skill="my-plugin:skill1")
        assert params.skill == "my-plugin:skill1"
        assert params.args == ""

    def test_missing_skill_raises(self) -> None:
        with pytest.raises(ValidationError):
            InvokeSkillParams()  # type: ignore[call-arg]

    def test_empty_skill_rejected(self) -> None:
        with pytest.raises(ValidationError):
            InvokeSkillParams(skill="")

    def test_clarification_mode_pattern(self) -> None:
        params = InvokeSkillParams(skill="s", clarification_mode="auto")
        assert params.clarification_mode == "auto"


# ---------------------------------------------------------------------------
# Command params
# ---------------------------------------------------------------------------


class TestSlashCommandParams:
    """SlashCommandParams validation."""

    def test_valid_cmd(self) -> None:
        params = SlashCommandParams(cmd="/exit")
        assert params.cmd == "/exit"

    def test_missing_cmd_raises(self) -> None:
        with pytest.raises(ValidationError):
            SlashCommandParams()  # type: ignore[call-arg]

    def test_empty_cmd_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SlashCommandParams(cmd="")


class TestRpcCommandParams:
    """RpcCommandParams validation."""

    def test_empty_params_valid(self) -> None:
        params = RpcCommandParams()
        assert params.command is None

    def test_with_command_and_payload(self) -> None:
        params = RpcCommandParams(command="autopilot_status", payload={})
        assert params.command == "autopilot_status"


# ---------------------------------------------------------------------------
# Empty-params methods
# ---------------------------------------------------------------------------


class TestEmptyParamsMethods:
    """Methods with no required fields should construct from no args."""

    @pytest.mark.parametrize(
        "model_cls",
        [
            DaemonStatusParams,
            SkillsListParams,
            ModelsListParams,
            McpStatusParams,
            DisconnectParams,
        ],
    )
    def test_constructs_with_no_args(self, model_cls: type) -> None:
        params = model_cls()
        # model_dump should succeed and return a dict
        assert isinstance(params.model_dump(), dict)


# ---------------------------------------------------------------------------
# Loop tree/prune/delete/reattach/detach — single loop_id required
# ---------------------------------------------------------------------------


class TestLoopIdParams:
    """Params that require only a loop_id."""

    @pytest.mark.parametrize(
        "model_cls",
        [LoopTreeParams, LoopDeleteParams, LoopReattachParams, LoopDetachParams],
    )
    def test_requires_loop_id(self, model_cls: type) -> None:
        with pytest.raises(ValidationError):
            model_cls()  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "model_cls",
        [LoopTreeParams, LoopDeleteParams, LoopReattachParams, LoopDetachParams],
    )
    def test_valid(self, model_cls: type) -> None:
        params = model_cls(loop_id="abc")
        assert params.loop_id == "abc"


class TestLoopPruneParams:
    """LoopPruneParams validation."""

    def test_valid_defaults(self) -> None:
        params = LoopPruneParams(loop_id="abc")
        assert params.keep_latest == 1

    def test_keep_latest_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            LoopPruneParams(loop_id="abc", keep_latest=0)


class TestLoopMessagesParams:
    """LoopMessagesParams validation."""

    def test_valid_defaults(self) -> None:
        params = LoopMessagesParams(loop_id="abc")
        assert params.limit == 100
        assert params.offset == 0

    def test_requires_loop_id(self) -> None:
        with pytest.raises(ValidationError):
            LoopMessagesParams()  # type: ignore[call-arg]


class TestLoopCardsFetchParams:
    """LoopCardsFetchParams validation."""

    def test_valid_with_loop_id(self) -> None:
        params = LoopCardsFetchParams(loop_id="abc")
        assert params.since is None

    def test_requires_loop_id(self) -> None:
        with pytest.raises(ValidationError):
            LoopCardsFetchParams()  # type: ignore[call-arg]


class TestLoopStateGetParams:
    """LoopStateGetParams validation."""

    def test_valid_with_loop_id(self) -> None:
        params = LoopStateGetParams(loop_id="abc")
        assert params.keys is None

    def test_with_keys(self) -> None:
        params = LoopStateGetParams(loop_id="abc", keys=["a", "b"])
        assert params.keys == ["a", "b"]


class TestConfigGetParams:
    """ConfigGetParams validation."""

    def test_empty_valid(self) -> None:
        params = ConfigGetParams()
        assert params.section is None

    def test_with_section(self) -> None:
        params = ConfigGetParams(section="providers")
        assert params.section == "providers"


class TestAuthParams:
    """AuthParams validation."""

    def test_empty_defaults_valid(self) -> None:
        params = AuthParams()
        assert params.access_key == ""
        assert params.secret_key == ""


# ---------------------------------------------------------------------------
# to_dict round-trip — params must serialize cleanly for the wire
# ---------------------------------------------------------------------------


class TestSerialization:
    """Param models serialize to JSON-safe dicts for the wire."""

    def test_loop_input_serializes(self) -> None:
        params = LoopInputParams(loop_id="abc", content="Hi", autonomous=True)
        dumped = params.model_dump(exclude_none=True)
        assert dumped["loop_id"] == "abc"
        assert dumped["content"] == "Hi"
        assert dumped["autonomous"] is True

    def test_subscribe_serializes(self) -> None:
        params = SubscribeParams(loop_id="abc", stream_delivery="batch")
        dumped = params.model_dump(exclude_none=True)
        assert dumped["stream_delivery"] == "batch"
