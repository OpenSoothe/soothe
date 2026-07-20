"""Regression tests for virtual-path handling in core.security.

These cover the bugs identified in the filesystem-unification audit:

* ``SecurityPolicy.evaluate`` denied every virtual workspace path because the
  ``path.startswith("/")`` check did not distinguish virtual from host.
* ``SecurityPolicy`` allowlist/blocklist used substring (``in``) matching, which
  produced false positives like ``/etc`` matching ``/tmp/x/etc/foo``.
* ``PathValidator._normalize_path`` rejected virtual ``/`` paths outright when
  ``allow_absolute=False``, breaking sandbox modes.
* ``PathValidator._check_workspace_boundary`` joined ``workspace / abs_path``,
  which silently discards the workspace.
"""

from __future__ import annotations

from pathlib import Path

from soothe_nano.security.path_security import PathValidator
from soothe_nano.security.policy_models import SecurityPolicy

# ---------------------------------------------------------------------------
# SecurityPolicy.evaluate
# ---------------------------------------------------------------------------


def test_policy_virtual_path_allowed_when_workspace_context_provided() -> None:
    """A virtual workspace path must not be denied just for starting with '/'."""
    policy = SecurityPolicy(name="sandbox", allow_absolute=False)
    decision = policy.evaluate("/CHANGELOG.md", "read", context={"workspace": "/some/workspace"})
    assert not any(v.violation_type == "absolute_path_not_allowed" for v in decision.violations)


def test_policy_host_absolute_etc_still_denied_under_sandbox() -> None:
    """A genuine host root (/etc) must still be denied when allow_absolute is False."""
    policy = SecurityPolicy(name="sandbox", allow_absolute=False)
    decision = policy.evaluate("/etc/passwd", "read", context={"workspace": "/some/workspace"})
    assert any(v.violation_type == "absolute_path_not_allowed" for v in decision.violations)


def test_policy_blocked_path_no_substring_false_positive() -> None:
    """``/etc`` blocked must NOT match ``/tmp/x/etc/foo`` (substring false positive)."""
    policy = SecurityPolicy(name="t", blocked_paths=frozenset({"/etc"}))
    decision = policy.evaluate("/tmp/x/etc/foo", "read")
    assert not any(v.violation_type == "blocked_path" for v in decision.violations)


def test_policy_blocked_path_component_prefix_still_works() -> None:
    """``/etc`` blocked must still match ``/etc/passwd`` (proper prefix)."""
    policy = SecurityPolicy(name="t", blocked_paths=frozenset({"/etc"}))
    decision = policy.evaluate("/etc/passwd", "read")
    assert any(v.violation_type == "blocked_path" for v in decision.violations)


def test_policy_blocked_path_sibling_with_shared_prefix_not_matched() -> None:
    """``/etc`` blocked must NOT match a sibling like ``/etcetera/foo``."""
    policy = SecurityPolicy(name="t", blocked_paths=frozenset({"/etc"}))
    decision = policy.evaluate("/etcetera/foo", "read")
    assert not any(v.violation_type == "blocked_path" for v in decision.violations)


def test_policy_allowed_paths_component_prefix() -> None:
    """Allowed paths use component-prefix, not substring."""
    policy = SecurityPolicy(name="t", allowed_paths=frozenset({"/safe"}))
    inside = policy.evaluate("/safe/file.txt", "read")
    sibling = policy.evaluate("/safety/file.txt", "read")
    assert inside.allowed is True
    assert sibling.allowed is False


# ---------------------------------------------------------------------------
# PathValidator._normalize_path / _check_workspace_boundary
# ---------------------------------------------------------------------------


def test_validator_virtual_path_accepted_under_sandbox(tmp_path: Path) -> None:
    """``/CHANGELOG.md`` under workspace must not trip ``allow_absolute=False``."""
    (tmp_path / "CHANGELOG.md").write_text("hi", encoding="utf-8")
    validator = PathValidator(workspace=tmp_path, allow_absolute=False)
    result = validator.validate("/CHANGELOG.md", operation="read")
    assert result.is_valid, result.message
    assert result.normalized_path == "CHANGELOG.md"


def test_validator_genuine_host_absolute_still_rejected_under_sandbox(tmp_path: Path) -> None:
    """``/etc/passwd`` (first segment is a host root) is rejected when allow_absolute=False."""
    validator = PathValidator(workspace=tmp_path, allow_absolute=False)
    result = validator.validate("/etc/passwd", operation="read")
    assert not result.is_valid
    assert result.violation_type in {"absolute_path_blocked", "blocked_system_path"}


def test_validator_workspace_boundary_handles_absolute_path(tmp_path: Path) -> None:
    """``_check_workspace_boundary`` must not silently allow an absolute path outside.

    The previous ``(self.workspace / abs).resolve()`` discarded the workspace
    when ``abs`` started with '/', producing a path equal to ``abs`` — and the
    boundary check then went through whatever ``relative_to`` happened to do.
    """
    outside = "/etc/passwd"
    validator = PathValidator(workspace=tmp_path, allow_absolute=True)
    # Direct boundary check (bypassing _normalize_path) must flag escape.
    result = validator._check_workspace_boundary(outside)
    assert result is not None
    assert result.violation_type == "workspace_boundary_violation"
