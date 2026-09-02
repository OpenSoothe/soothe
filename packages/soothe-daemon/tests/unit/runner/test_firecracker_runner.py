"""Unit tests for Firecracker microVM runner mode (RFC-221).

Verifies factory mode selection, fail-fast validation, config validation,
and that firecracker imports do not leak into other runner modes.
No real microVMs or vsock required — all mock-based.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from soothe.config import SootheConfig

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import (
    FirecrackerConfig,
    ProcessPoolConfig,
    RayConfig,
    ThreadPoolConfig,
)
from soothe_daemon.runner.factory import LoopRunnerFactory
from soothe_daemon.runner.thread_runner import ThreadLoopRunner


def _fc_config(
    *,
    firecracker_enabled: bool = True,
    worker_pool_enabled: bool = False,
    thread_pool_enabled: bool = False,
    distributed: bool = False,
    binary_path: str = "/usr/local/bin/firecracker",
    kernel_path: str = "/var/lib/soothe/vmlinux",
    rootfs_path: str = "/var/lib/soothe/rootfs.ext4",
) -> tuple[SootheDaemonConfig, SootheConfig]:
    """Create daemon and agent configs with specific runner mode settings."""
    daemon_cfg = SootheDaemonConfig()
    daemon_cfg.firecracker = FirecrackerConfig(
        enabled=firecracker_enabled,
        firecracker_binary_path=binary_path,
        kernel_image_path=kernel_path,
        rootfs_image_path=rootfs_path,
    )
    daemon_cfg.process_pool = ProcessPoolConfig(enabled=worker_pool_enabled)
    daemon_cfg.thread_pool = ThreadPoolConfig(enabled=thread_pool_enabled)
    daemon_cfg.ray = RayConfig(enabled=distributed)
    agent_cfg = SootheConfig()
    return daemon_cfg, agent_cfg


class TestLoopRunnerFactoryFirecrackerMode:
    """Factory creates FirecrackerLoopRunner when firecracker.enabled=True."""

    def test_create_runner_returns_firecracker_runner_when_enabled(self) -> None:
        """When firecracker.enabled=True (and others disabled), FirecrackerLoopRunner is used."""
        daemon_cfg, agent_cfg = _fc_config()

        fake_runner_instance = MagicMock()
        mock_fc_runner_cls = MagicMock(return_value=fake_runner_instance)
        fake_fc_runner_mod = MagicMock()
        fake_fc_runner_mod.FirecrackerLoopRunner = mock_fc_runner_cls
        fake_fc_runner_mod.FirecrackerWorkerPool = MagicMock()

        with patch.dict(
            sys.modules,
            {"soothe_daemon.runner.firecracker_runner": fake_fc_runner_mod},
        ):
            with (
                patch("os.path.isfile", return_value=True),
                patch("shutil.which", return_value="/usr/local/bin/firecracker"),
            ):
                factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
                runner = factory.create_runner("loop-fc")

        mock_fc_runner_cls.assert_called_once_with("loop-fc", agent_cfg, daemon_cfg)
        assert runner is fake_runner_instance

    def test_raises_filenotfounderror_when_binary_missing(self) -> None:
        """Construction must fail fast when the firecracker binary is missing."""
        daemon_cfg, agent_cfg = _fc_config()

        with patch("shutil.which", return_value=None), patch("os.path.isfile", return_value=False):
            with pytest.raises(FileNotFoundError, match="Firecracker binary not found"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_filenotfounderror_when_kernel_missing(self) -> None:
        """Construction must fail fast when the kernel image is missing."""
        daemon_cfg, agent_cfg = _fc_config()

        # Binary found, but kernel not found
        def _isfile(path: str) -> bool:
            return "firecracker" in path  # binary path exists, kernel/rootfs don't

        with (
            patch("shutil.which", return_value="/usr/local/bin/firecracker"),
            patch("os.path.isfile", side_effect=_isfile),
        ):
            with pytest.raises(FileNotFoundError, match="Kernel image not found"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_filenotfounderror_when_rootfs_missing(self) -> None:
        """Construction must fail fast when the rootfs image is missing."""
        daemon_cfg, agent_cfg = _fc_config()

        # Binary and kernel found, rootfs not found
        def _isfile(path: str) -> bool:
            return "firecracker" in path or "vmlinux" in path

        with (
            patch("shutil.which", return_value="/usr/local/bin/firecracker"),
            patch("os.path.isfile", side_effect=_isfile),
        ):
            with pytest.raises(FileNotFoundError, match="Rootfs image not found"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_firecracker_mode_does_not_import_on_other_modes(self) -> None:
        """Creating a factory or runner in thread/process/ray mode must not
        import firecracker_runner."""
        daemon_cfg, agent_cfg = _fc_config(firecracker_enabled=False, thread_pool_enabled=True)
        with patch.dict(sys.modules, {"soothe_daemon.runner.firecracker_runner": None}):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-thread")
        # If we got here without ImportError, firecracker_runner was never imported
        assert isinstance(runner, ThreadLoopRunner)


class TestFirecrackerConfigValidation:
    """Tests for validate_runner_mode() with firecracker mode."""

    def test_firecracker_valid_when_only_one_enabled(self) -> None:
        """Firecracker is valid when only it is enabled."""
        daemon_cfg, agent_cfg = _fc_config()
        with (
            patch("os.path.isfile", return_value=True),
            patch("shutil.which", return_value="/usr/local/bin/firecracker"),
        ):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "firecracker"

    def test_raises_value_error_when_firecracker_and_worker_pool_enabled(self) -> None:
        """Firecracker + process_pool is rejected."""
        daemon_cfg, agent_cfg = _fc_config(worker_pool_enabled=True)
        with pytest.raises(ValueError, match="Multiple runner modes enabled"):
            LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_value_error_when_firecracker_and_thread_pool_enabled(self) -> None:
        """Firecracker + thread_pool is rejected."""
        daemon_cfg, agent_cfg = _fc_config(thread_pool_enabled=True)
        with pytest.raises(ValueError, match="Multiple runner modes enabled"):
            LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_value_error_when_firecracker_and_distributed_enabled(self) -> None:
        """Firecracker + ray is rejected."""
        daemon_cfg, agent_cfg = _fc_config(distributed=True)
        with pytest.raises(ValueError, match="Multiple runner modes enabled"):
            LoopRunnerFactory(daemon_cfg, agent_cfg)


class TestFirecrackerIdentityValidation:
    """Identity + firecracker mode is rejected at factory construction."""

    def test_raises_when_identity_enabled_with_firecracker(self) -> None:
        from soothe.identity.runtime import IdentityConfig, IdentityRuntime

        daemon_cfg, agent_cfg = _fc_config()
        daemon_cfg.identity = IdentityConfig(enabled=True)

        identity_runtime = IdentityRuntime(
            service=MagicMock(),
            config=daemon_cfg.identity,
        )

        with (
            patch("os.path.isfile", return_value=True),
            patch("shutil.which", return_value="/usr/local/bin/firecracker"),
        ):
            with pytest.raises(ValueError, match="Identity service requires thread_pool mode"):
                LoopRunnerFactory(daemon_cfg, agent_cfg, identity_runtime=identity_runtime)


class TestFirecrackerConfigDefaults:
    """Default FirecrackerConfig has enabled=False and sensible VM defaults."""

    def test_default_config_has_firecracker_disabled(self) -> None:
        """Default config disables firecracker (thread_pool is the default mode)."""
        daemon_cfg = SootheDaemonConfig()
        assert daemon_cfg.firecracker.enabled is False
        assert daemon_cfg.thread_pool.enabled is True

    def test_default_firecracker_config_values(self) -> None:
        """Default VM sizing and paths are sensible."""
        fc = FirecrackerConfig()
        assert fc.min_pool_size == 1
        assert fc.max_pool_size == 4
        assert fc.vsock_port_base == 1024
        assert fc.vm_cpu_count == 2
        assert fc.vm_mem_mib == 2048
        assert fc.workspace_mount_mode == "virtiofs"
        assert fc.firecracker_binary_path == "firecracker"

    def test_firecracker_config_get_effective_pool_size(self) -> None:
        """get_effective_pool_size returns max(min, max)."""
        fc = FirecrackerConfig(min_pool_size=3, max_pool_size=2)
        assert fc.get_effective_pool_size() == 3


class TestFirecrackerLoopRunnerProtocol:
    """FirecrackerLoopRunner satisfies LoopRunnerProtocol structure."""

    def test_runner_has_protocol_methods(self) -> None:
        """FirecrackerLoopRunner exposes run/cancel/is_idle/force_kill/set_clarification_mode."""
        from soothe_daemon.runner.firecracker_runner import FirecrackerLoopRunner

        runner = FirecrackerLoopRunner.__new__(FirecrackerLoopRunner)
        # Structural check: all protocol methods exist as callables
        for method_name in ("run", "cancel", "is_idle", "force_kill", "set_clarification_mode"):
            assert hasattr(runner, method_name), f"Missing protocol method: {method_name}"
            assert callable(getattr(runner, method_name))

    def test_set_clarification_mode_returns_false(self) -> None:
        """set_clarification_mode returns False (VM isolation, like ProcessLoopRunner)."""
        from soothe_daemon.runner.firecracker_runner import FirecrackerLoopRunner

        runner = FirecrackerLoopRunner.__new__(FirecrackerLoopRunner)
        runner._loop_id = "test-loop"
        runner._pool = None
        assert runner.set_clarification_mode("auto") is False
