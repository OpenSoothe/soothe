"""Unit tests for BoxLite container runner mode (RFC-221).

Verifies factory mode selection, fail-fast validation, config validation,
and that boxlite imports do not leak into other runner modes.
No real boxlite containers required — all mock-based.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from soothe.config import SootheConfig

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import BoxLiteConfig, LoopRunnerConfig
from soothe_daemon.runner.factory import LoopRunnerFactory
from soothe_daemon.runner.thread_runner import ThreadLoopRunner


def _bl_config(
    *,
    runner_mode: str = "boxlite",
    container_image: str = "soothe/worker:latest",
    rootfs_path: str = "",
) -> tuple[SootheDaemonConfig, SootheConfig]:
    """Create daemon and agent configs with boxlite runner mode.

    Args:
        runner_mode: Runner mode string (default 'boxlite').
        container_image: OCI image to use for worker containers.
        rootfs_path: Optional local OCI layout directory.
    """
    daemon_cfg = SootheDaemonConfig(
        loop_runner=LoopRunnerConfig(
            runner_mode=runner_mode,
            boxlite=BoxLiteConfig(
                container_image=container_image,
                rootfs_path=rootfs_path,
            ),
        )
    )
    agent_cfg = SootheConfig()
    return daemon_cfg, agent_cfg


class TestLoopRunnerFactoryBoxLiteMode:
    """Factory creates BoxLiteLoopRunner when runner_mode='boxlite'."""

    def test_create_runner_returns_boxlite_runner_when_enabled(self) -> None:
        """When runner_mode='boxlite', BoxLiteLoopRunner is used."""
        daemon_cfg, agent_cfg = _bl_config()

        fake_runner_instance = MagicMock()
        mock_bl_runner_cls = MagicMock(return_value=fake_runner_instance)
        fake_bl_runner_mod = MagicMock()
        fake_bl_runner_mod.BoxLiteLoopRunner = mock_bl_runner_cls
        fake_bl_runner_mod.BoxLiteWorkerPool = MagicMock()

        with patch.dict(
            sys.modules,
            {"soothe_daemon.runner.boxlite_runner": fake_bl_runner_mod},
        ):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-bl")

        mock_bl_runner_cls.assert_called_once_with("loop-bl", agent_cfg, daemon_cfg)
        assert runner is fake_runner_instance

    def test_raises_valueerror_when_image_and_rootfs_not_set(self) -> None:
        """Construction must fail fast when neither container_image nor rootfs_path is set."""
        daemon_cfg, agent_cfg = _bl_config(container_image="", rootfs_path="")

        with pytest.raises(ValueError, match="Container image or rootfs_path not set"):
            LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_boxlite_mode_does_not_import_on_other_modes(self) -> None:
        """Creating a factory or runner in thread/process/ray mode must not
        import boxlite_runner."""
        daemon_cfg, agent_cfg = _bl_config(runner_mode="thread_pool")
        with patch.dict(sys.modules, {"soothe_daemon.runner.boxlite_runner": None}):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-thread")
        assert isinstance(runner, ThreadLoopRunner)

    def test_rootfs_path_alone_is_valid(self) -> None:
        """rootfs_path without container_image should pass validation."""
        daemon_cfg, agent_cfg = _bl_config(container_image="", rootfs_path="/tmp/oci-layout")

        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "boxlite"


class TestBoxLiteConfigValidation:
    """Tests for loop_runner.runner_mode field with boxlite mode."""

    def test_boxlite_valid_when_selected(self) -> None:
        """BoxLite is valid when runner_mode='boxlite'."""
        daemon_cfg, agent_cfg = _bl_config()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "boxlite"

    def test_boxlite_invalid_when_thread_pool_selected(self) -> None:
        """runner_mode='thread_pool' does not enter boxlite branch."""
        daemon_cfg, agent_cfg = _bl_config(runner_mode="thread_pool")
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "thread_pool"


class TestBoxLiteIdentityValidation:
    """Identity + boxlite mode is rejected at factory construction."""

    def test_raises_when_identity_enabled_with_boxlite(self) -> None:
        from soothe.identity.runtime import IdentityConfig, IdentityRuntime

        daemon_cfg, agent_cfg = _bl_config()
        daemon_cfg.identity = IdentityConfig(enabled=True)

        identity_runtime = IdentityRuntime(
            service=MagicMock(),
            config=daemon_cfg.identity,
        )

        with pytest.raises(ValueError, match="Identity service requires thread_pool mode"):
            LoopRunnerFactory(daemon_cfg, agent_cfg, identity_runtime=identity_runtime)


class TestBoxLiteConfigDefaults:
    """Default BoxLiteConfig has sensible container defaults."""

    def test_default_config_has_thread_pool_mode(self) -> None:
        """Default config selects thread_pool mode (not boxlite)."""
        daemon_cfg = SootheDaemonConfig()
        assert daemon_cfg.loop_runner.runner_mode == "thread_pool"

    def test_default_boxlite_config_values(self) -> None:
        """Default container sizing and paths are sensible."""
        bl = BoxLiteConfig()
        assert bl.min_pool_size == 1
        assert bl.max_pool_size == 4
        assert bl.container_cpu_count == 2
        assert bl.container_mem_mib == 2048
        assert bl.workspace_mount_mode == "bind"
        assert bl.container_image == ""
        assert bl.rootfs_path == ""

    def test_boxlite_config_get_effective_pool_size(self) -> None:
        """get_effective_pool_size returns max(min, max)."""
        bl = BoxLiteConfig(min_pool_size=2, max_pool_size=8)
        assert bl.get_effective_pool_size() == 8

    def test_boxlite_config_clamps_min_above_max(self) -> None:
        """get_effective_pool_size ensures max >= min."""
        bl = BoxLiteConfig(min_pool_size=8, max_pool_size=2)
        assert bl.get_effective_pool_size() == 8


class TestBoxLiteCrossPlatform:
    """BoxLite runner is cross-platform (no platform restriction)."""

    def test_boxlite_works_on_macos(self) -> None:
        """Unlike firecracker, boxlite does NOT raise on macOS."""
        daemon_cfg, agent_cfg = _bl_config()

        with (
            patch("sys.platform", "darwin"),
        ):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "boxlite"

    def test_boxlite_works_on_linux(self) -> None:
        """BoxLite works on Linux."""
        daemon_cfg, agent_cfg = _bl_config()

        with (
            patch("sys.platform", "linux"),
        ):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        assert factory._mode == "boxlite"
