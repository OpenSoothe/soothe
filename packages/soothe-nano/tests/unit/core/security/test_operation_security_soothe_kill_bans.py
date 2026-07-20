"""Unit tests for Soothe-targeting shell command bans (IG-665)."""

from __future__ import annotations

import pytest
from soothe_sdk.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityRequest,
)

from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity


@pytest.mark.parametrize(
    "command",
    [
        'pkill -9 -f "pytest packages/soothe"',
        "pkill -f soothed",
        "killall soothe",
        "soothed stop",
        "soothed restart",
    ],
)
def test_operation_security_blocks_soothe_process_wipes(command: str) -> None:
    ev = WorkspaceToolOperationSecurity()
    decision = ev.evaluate(
        OperationSecurityRequest(
            action_type="tool_call",
            tool_name="run_command",
            tool_args={"command": command},
            operation_kind="shell_execute",
            command=command,
        ),
        OperationSecurityContext(workspace=None, security_config=None),
    )
    assert decision.verdict == "deny"
    assert decision.rule_id is not None
    assert "soothe" in decision.rule_id or "soothed" in decision.rule_id


def test_operation_security_allows_unrelated_pkill() -> None:
    ev = WorkspaceToolOperationSecurity()
    command = "pkill -f my_unrelated_worker"
    decision = ev.evaluate(
        OperationSecurityRequest(
            action_type="tool_call",
            tool_name="run_command",
            tool_args={"command": command},
            operation_kind="shell_execute",
            command=command,
        ),
        OperationSecurityContext(workspace=None, security_config=None),
    )
    assert decision.verdict == "allow"
