"""Unit tests for LoopRunnerFactory (RFC-221).

Verifies correct runner type selection and Ray validation at construction time.
No real subprocesses or Ray cluster required.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from soothe.config import SootheConfig

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import LoopRunnerConfig
from soothe_daemon.runner.factory import LoopRunnerFactory
from soothe_daemon.runner.pool_runner import ProcessLoopRunner
from soothe_daemon.runner.thread_runner import ThreadLoopRunner


def _config(runner_mode: str = "process_pool") -> tuple[SootheDaemonConfig, SootheConfig]:
    """Create daemon and agent configs with a specific runner_mode.

    Args:
        runner_mode: One of 'thread_pool', 'process_pool', 'ray', 'firecracker'.
    """
    daemon_cfg = SootheDaemonConfig(loop_runner=LoopRunnerConfig(runner_mode=runner_mode))
    agent_cfg = SootheConfig()
    return daemon_cfg, agent_cfg


class TestLoopRunnerFactoryPoolMode:
    """Factory creates ProcessLoopRunner when runner_mode='process_pool'."""

    def test_create_runner_returns_pool_runner_when_explicitly_enabled(self) -> None:
        """When runner_mode='process_pool', ProcessLoopRunner is used."""
        daemon_cfg, agent_cfg = _config(runner_mode="process_pool")
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, ProcessLoopRunner)

    def test_create_runner_unique_per_loop_id(self) -> None:
        daemon_cfg, agent_cfg = _config(runner_mode="process_pool")
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        r1 = factory.create_runner("loop-1")
        r2 = factory.create_runner("loop-2")
        assert r1 is not r2
        assert r1._loop_id == "loop-1"
        assert r2._loop_id == "loop-2"


class TestLoopRunnerFactoryThreadMode:
    """Factory creates ThreadLoopRunner when runner_mode='thread_pool'."""

    def test_create_runner_returns_thread_runner_when_thread_pool_enabled(self) -> None:
        """When runner_mode='thread_pool', ThreadLoopRunner is used."""
        daemon_cfg, agent_cfg = _config(runner_mode="thread_pool")
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, ThreadLoopRunner)

    def test_thread_mode_does_not_import_ray(self) -> None:
        """Creating a factory or runner in thread mode must not import Ray."""
        daemon_cfg, agent_cfg = _config(runner_mode="thread_pool")
        with patch.dict(sys.modules, {"ray": None}):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-xyz")
        assert isinstance(runner, ThreadLoopRunner)


class TestLoopRunnerFactoryDistributedMode:
    """Factory creates RayLoopRunner when runner_mode='ray'; fails fast if Ray absent."""

    def test_raises_import_error_when_ray_not_installed(self) -> None:
        """Construction must fail fast when Ray is unavailable in ray mode."""
        daemon_cfg, agent_cfg = _config(runner_mode="ray")
        with patch.dict(sys.modules, {"ray": None}):
            with pytest.raises(ImportError, match="Ray is required"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_create_runner_returns_ray_runner_when_ray_available(self) -> None:
        """create_runner() returns a RayLoopRunner when Ray is importable."""
        mock_ray = MagicMock()
        fake_runner_instance = MagicMock()
        mock_ray_runner_cls = MagicMock(return_value=fake_runner_instance)

        fake_ray_runner_mod = MagicMock()
        fake_ray_runner_mod.RayLoopRunner = mock_ray_runner_cls

        daemon_cfg, agent_cfg = _config(runner_mode="ray")
        with patch.dict(
            sys.modules,
            {
                "ray": mock_ray,
                "soothe_daemon.runner.ray_runner": fake_ray_runner_mod,
                "soothe_daemon.runner.ray_actor": MagicMock(),
            },
        ):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-distributed")

        mock_ray_runner_cls.assert_called_once_with("loop-distributed", agent_cfg)
        assert runner is fake_runner_instance


class TestLoopRunnerFactoryDefaultConfig:
    """Default SootheDaemonConfig has loop_runner.runner_mode='thread_pool'."""

    def test_default_config_has_thread_pool_mode(self) -> None:
        """Default config selects thread pool (ThreadLoopRunner)."""
        daemon_cfg = SootheDaemonConfig()
        agent_cfg = SootheConfig()
        assert daemon_cfg.loop_runner.runner_mode == "thread_pool"
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-default")
        assert isinstance(runner, ThreadLoopRunner)

    def test_explicit_worker_pool_returns_pool_runner(self) -> None:
        """Setting runner_mode='process_pool' returns ProcessLoopRunner."""
        daemon_cfg, agent_cfg = _config(runner_mode="process_pool")
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-local")
        assert isinstance(runner, ProcessLoopRunner)


class TestLoopRunnerFactoryIdentityValidation:
    """Identity + process_pool mode is rejected at factory construction."""

    def test_raises_when_identity_enabled_with_worker_pool(self) -> None:
        from soothe.identity.runtime import IdentityConfig, IdentityRuntime

        daemon_cfg = SootheDaemonConfig(loop_runner=LoopRunnerConfig(runner_mode="process_pool"))
        daemon_cfg.identity = IdentityConfig(enabled=True)
        agent_cfg = SootheConfig()

        identity_runtime = IdentityRuntime(
            service=MagicMock(),
            config=daemon_cfg.identity,
        )

        with pytest.raises(ValueError, match="Identity service requires thread_pool mode"):
            LoopRunnerFactory(daemon_cfg, agent_cfg, identity_runtime=identity_runtime)


class TestLoopRunnerFactoryModeValidation:
    """Tests for loop_runner.runner_mode field validation."""

    def test_thread_pool_valid(self) -> None:
        """Thread pool is valid when runner_mode='thread_pool' (also default)."""
        daemon_cfg = SootheDaemonConfig(loop_runner=LoopRunnerConfig(runner_mode="thread_pool"))
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-thread")
        assert isinstance(runner, ThreadLoopRunner)

    def test_process_pool_valid(self) -> None:
        """Process pool is valid when runner_mode='process_pool'."""
        daemon_cfg = SootheDaemonConfig(loop_runner=LoopRunnerConfig(runner_mode="process_pool"))
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-pool")
        assert isinstance(runner, ProcessLoopRunner)

    def test_invalid_mode_rejected_by_pydantic(self) -> None:
        """Invalid runner_mode string is rejected by the Literal type."""
        with pytest.raises(Exception):  # pydantic ValidationError
            SootheDaemonConfig(loop_runner=LoopRunnerConfig(runner_mode="invalid_mode"))
