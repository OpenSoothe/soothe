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
from soothe_daemon.config.models import FirecrackerConfig, LoopRunnerConfig
from soothe_daemon.runner.factory import LoopRunnerFactory
from soothe_daemon.runner.thread_runner import ThreadLoopRunner


def _fc_config(
    *,
    runner_mode: str = "firecracker",
    binary_path: str = "/usr/local/bin/firecracker",
    kernel_path: str = "/var/lib/soothe/vmlinux",
    rootfs_path: str = "/var/lib/soothe/rootfs.ext4",
) -> tuple[SootheDaemonConfig, SootheConfig]:
    """Create daemon and agent configs with firecracker runner mode.

    Args:
        runner_mode: Runner mode string (default 'firecracker').
        binary_path: Path to the firecracker binary.
        kernel_path: Path to the kernel image.
        rootfs_path: Path to the rootfs image.
    """
    daemon_cfg = SootheDaemonConfig(
        loop_runner=LoopRunnerConfig(
            runner_mode=runner_mode,
            firecracker=FirecrackerConfig(
                firecracker_binary_path=binary_path,
                kernel_image_path=kernel_path,
                rootfs_image_path=rootfs_path,
            ),
        )
    )
    agent_cfg = SootheConfig()
    return daemon_cfg, agent_cfg


class TestLoopRunnerFactoryFirecrackerMode:
    """Factory creates FirecrackerLoopRunner when runner_mode='firecracker'."""

    def test_create_runner_returns_firecracker_runner_when_enabled(self) -> None:
        """When runner_mode='firecracker', FirecrackerLoopRunner is used."""
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
                patch("sys.platform", "linux"),
                patch("os.path.isfile", return_value=True),
                patch("shutil.which", return_value="/usr/local/bin/firecracker"),
            ):
                factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
                runner = factory.create_runner("loop-fc")

        mock_fc_runner_cls.assert_called_once_with("loop-fc", agent_cfg, daemon_cfg)
        assert runner is fake_runner_instance

    def test_raises_runtimeerror_on_non_linux_host(self) -> None:
        """Construction must fail with RuntimeError on non-Linux hosts."""
        daemon_cfg, agent_cfg = _fc_config()

        with patch("sys.platform", "darwin"):
            with pytest.raises(RuntimeError, match="Linux only"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_filenotfounderror_when_binary_missing(self) -> None:
        """Construction must fail fast when the firecracker binary is missing."""
        daemon_cfg, agent_cfg = _fc_config()

        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value=None),
            patch("os.path.isfile", return_value=False),
        ):
            with pytest.raises(FileNotFoundError, match="Firecracker binary not found"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_filenotfounderror_when_kernel_missing(self) -> None:
        """Construction must fail fast when the kernel image is missing."""
        daemon_cfg, agent_cfg = _fc_config()

        def _isfile(path: str) -> bool:
            return "firecracker" in path  # binary path exists, kernel/rootfs don't

        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/local/bin/firecracker"),
            patch("os.path.isfile", side_effect=_isfile),
        ):
            with pytest.raises(FileNotFoundError, match="Kernel image not found"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_filenotfounderror_when_rootfs_missing(self) -> None:
        """Construction must fail fast when the rootfs image is missing."""
        daemon_cfg, agent_cfg = _fc_config()

        def _isfile(path: str) -> bool:
            return "firecracker" in path or "vmlinux" in path

        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value="/usr/local/bin/firecracker"),
            patch("os.path.isfile", side_effect=_isfile),
        ):
            with pytest.raises(FileNotFoundError, match="Rootfs image not found"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_firecracker_mode_does_not_import_on_other_modes(self) -> None:
        """Creating a factory or runner in thread/process/ray mode must not
        import firecracker_runner."""
        daemon_cfg, agent_cfg = _fc_config(runner_mode="thread_pool")
        with patch.dict(sys.modules, {"soothe_daemon.runner.firecracker_runner": None}):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-thread")
        assert isinstance(runner, ThreadLoopRunner)


class TestFirecrackerConfigValidation:
    """Tests for loop_runner.runner_mode field with firecracker mode."""

    def test_firecracker_valid_when_selected(self) -> None:
        """Firecracker is valid when runner_mode='firecracker' on Linux."""
        daemon_cfg, agent_cfg = _fc_config()
        with (
            patch("sys.platform", "linux"),
            patch("os.path.isfile", return_value=True),
            patch("shutil.which", return_value="/usr/local/bin/firecracker"),
        ):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "firecracker"

    def test_firecracker_invalid_when_thread_pool_selected(self) -> None:
        """runner_mode='thread_pool' does not enter firecracker branch."""
        daemon_cfg, agent_cfg = _fc_config(runner_mode="thread_pool")
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "thread_pool"


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
    """Default FirecrackerConfig has sensible VM defaults."""

    def test_default_config_has_thread_pool_mode(self) -> None:
        """Default config selects thread_pool mode (not firecracker)."""
        daemon_cfg = SootheDaemonConfig()
        assert daemon_cfg.loop_runner.runner_mode == "thread_pool"

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
