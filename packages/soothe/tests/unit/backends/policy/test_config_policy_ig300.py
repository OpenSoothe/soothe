"""IG-300: ConfigDrivenPolicy filesystem boundary + metadata path extraction."""

from pathlib import Path
from types import SimpleNamespace

from soothe.core.persistence.config_policy import ConfigDrivenPolicy, _extract_required_permission
from soothe.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
)


def _security(
    *,
    allow_out: bool = False,
    require_approval_out: bool = True,
    allowed: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        allow_paths_outside_workspace=allow_out,
        require_approval_for_outside_paths=require_approval_out,
        denied_paths=[],
        allowed_paths=allowed or ["**"],
        denied_file_types=[],
        require_approval_for_file_types=[],
        whitelist_paths_bypass=[],
        whitelist_commands_bypass=[],
    )


def test_glob_denied_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir=str(ws))
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        thread_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="glob",
        tool_args={"path": str(other), "pattern": "*.py"},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "deny"
    assert "outside workspace" in d.reason


def test_read_file_allowed_inside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    f = ws / "a.txt"
    f.write_text("hi", encoding="utf-8")

    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir=str(ws))
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(
            frozenset([Permission("fs", "read", "*"), Permission("fs", "write", "*")])
        ),
        thread_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"file_path": str(f)},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "allow"


def test_outside_path_need_approval_when_configured(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    cfg = SimpleNamespace(
        security=_security(allow_out=True, require_approval_out=True),
        workspace_dir=str(ws),
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        thread_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": str(other / "x.txt")},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "need_approval"


def test_outside_allowed_when_flag_true_and_no_approval_required(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    cfg = SimpleNamespace(
        security=_security(allow_out=True, require_approval_out=False),
        workspace_dir=str(ws),
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        thread_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": str(other / "x.txt")},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "allow"


def test_denied_by_allowed_paths_whitelist(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = SimpleNamespace(
        security=SimpleNamespace(
            allow_paths_outside_workspace=True,
            require_approval_for_outside_paths=False,
            denied_paths=[],
            allowed_paths=["/only/here/**"],
            denied_file_types=[],
            require_approval_for_file_types=[],
        ),
        workspace_dir=str(ws),
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        thread_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": str(ws / "a.txt")},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "deny"
    assert "allowed pattern" in d.reason


def test_extract_required_permission_uses_file_path() -> None:
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"file_path": "/tmp/x"},
    )
    perm = _extract_required_permission(action)
    assert perm is not None
    assert perm.scope == "/tmp/x"


def test_run_background_denied_for_dangerous_command() -> None:
    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir="/tmp/ws")
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("shell", "execute", "*")])),
        thread_id="t1",
        workspace="/tmp/ws",
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="run_background",
        tool_args={"command": "rm -rf /"},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "deny"
    assert "Command blocked by security rule" in d.reason


def test_sensitive_system_path_denied_even_if_allowed_paths_wildcard(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = SimpleNamespace(
        security=_security(allow_out=True, require_approval_out=False), workspace_dir=str(ws)
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        thread_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": "/etc/hosts"},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "deny"
    assert "sensitive system pattern" in d.reason


def test_git_local_operation_allowed_but_remote_denied() -> None:
    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir="/tmp/ws")
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("shell", "execute", "*")])),
        thread_id="t1",
        workspace="/tmp/ws",
    )

    local = ActionRequest(
        action_type="tool_call",
        tool_name="run_command",
        tool_args={"command": "git status"},
    )
    remote = ActionRequest(
        action_type="tool_call",
        tool_name="run_command",
        tool_args={"command": "git push origin main"},
    )

    local_decision = policy.check(local, ctx)
    remote_decision = policy.check(remote, ctx)
    assert local_decision.verdict == "allow"
    assert remote_decision.verdict == "deny"
    assert "security rule" in remote_decision.reason


def test_git_remote_read_sync_operations_allowed() -> None:
    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir="/tmp/ws")
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("shell", "execute", "*")])),
        thread_id="t1",
        workspace="/tmp/ws",
    )

    commands = [
        "git fetch origin",
        "git pull origin main",
        "git clone https://example.com/repo.git",
    ]
    for command in commands:
        decision = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="run_command",
                tool_args={"command": command},
            ),
            ctx,
        )
        assert decision.verdict == "allow"


def test_path_whitelist_bypass_overrides_default_deny() -> None:
    cfg = SimpleNamespace(
        security=SimpleNamespace(
            **{
                **_security(allow_out=False).__dict__,
                "whitelist_paths_bypass": ["/etc/**", "/private/etc/**"],
            }
        ),
        workspace_dir="/tmp/ws",
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        thread_id="t1",
        workspace="/tmp/ws",
    )
    decision = policy.check(
        ActionRequest(
            action_type="tool_call",
            tool_name="read_file",
            tool_args={"path": "/etc/hosts"},
        ),
        ctx,
    )
    assert decision.verdict == "allow"


def test_command_whitelist_bypass_overrides_default_deny() -> None:
    cfg = SimpleNamespace(
        security=SimpleNamespace(
            **{
                **_security(allow_out=False).__dict__,
                "whitelist_commands_bypass": [r"\bgit\s+push\b"],
            }
        ),
        workspace_dir="/tmp/ws",
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("shell", "execute", "*")])),
        thread_id="t1",
        workspace="/tmp/ws",
    )
    decision = policy.check(
        ActionRequest(
            action_type="tool_call",
            tool_name="run_command",
            tool_args={"command": "git push origin main"},
        ),
        ctx,
    )
    assert decision.verdict == "allow"
