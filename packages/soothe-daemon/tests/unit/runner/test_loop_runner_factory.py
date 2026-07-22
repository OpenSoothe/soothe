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
from soothe_daemon.config.models import DistributedConfig, ThreadPoolConfig, WorkerPoolConfig
from soothe_daemon.runner.factory import LoopRunnerFactory
from soothe_daemon.runner.pool_runner import PoolLoopRunner
from soothe_daemon.runner.thread_runner import ThreadLoopRunner


def _config(
    distributed: bool = False, worker_pool_enabled: bool = True, thread_pool_enabled: bool = False
) -> tuple[SootheDaemonConfig, SootheConfig]:
    """Create daemon and agent configs with specific distribution and pool settings."""
    daemon_cfg = SootheDaemonConfig()
    daemon_cfg.distributed = DistributedConfig(enabled=distributed)
    daemon_cfg.worker_pool = WorkerPoolConfig(enabled=worker_pool_enabled)
    daemon_cfg.thread_pool = ThreadPoolConfig(enabled=thread_pool_enabled)
    agent_cfg = SootheConfig()
    return daemon_cfg, agent_cfg


class TestLoopRunnerFactoryPoolMode:
    """Factory creates PoolLoopRunner when worker_pool.enabled=True."""

    def test_create_runner_returns_pool_runner_when_explicitly_enabled(self) -> None:
        """When worker_pool.enabled=True (and thread_pool disabled), PoolLoopRunner is used."""
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=True)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=False)
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, PoolLoopRunner)

    def test_create_runner_unique_per_loop_id(self) -> None:
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=True)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=False)
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        r1 = factory.create_runner("loop-1")
        r2 = factory.create_runner("loop-2")
        assert r1 is not r2
        assert r1._loop_id == "loop-1"
        assert r2._loop_id == "loop-2"


class TestLoopRunnerFactoryThreadMode:
    """Factory creates ThreadLoopRunner when thread_pool.enabled=True."""

    def test_create_runner_returns_thread_runner_when_thread_pool_enabled(self) -> None:
        """When thread pool enabled, ThreadLoopRunner is used."""
        daemon_cfg, agent_cfg = _config(
            distributed=False, worker_pool_enabled=False, thread_pool_enabled=True
        )
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, ThreadLoopRunner)

    def test_thread_mode_does_not_import_ray(self) -> None:
        """Creating a factory or runner in thread mode must not import Ray."""
        # Ensure ray is not in sys.modules at all after factory creation
        daemon_cfg, agent_cfg = _config(
            distributed=False, worker_pool_enabled=False, thread_pool_enabled=True
        )
        with patch.dict(sys.modules, {"ray": None}):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-xyz")
        assert isinstance(runner, ThreadLoopRunner)


class TestLoopRunnerFactoryDistributedMode:
    """Factory creates RayLoopRunner when distributed.enabled=True; fails fast if Ray absent."""

    def test_raises_import_error_when_ray_not_installed(self) -> None:
        """Construction must fail fast when Ray is unavailable in distributed mode."""
        daemon_cfg, agent_cfg = _config(distributed=True, worker_pool_enabled=False)
        with patch.dict(sys.modules, {"ray": None}):
            with pytest.raises(ImportError, match="Ray is required"):
                LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_create_runner_returns_ray_runner_when_ray_available(self) -> None:
        """create_runner() returns a RayLoopRunner when Ray is importable."""
        mock_ray = MagicMock()
        fake_runner_instance = MagicMock()
        mock_ray_runner_cls = MagicMock(return_value=fake_runner_instance)

        # Provide a fake ray_runner module so the lazy import inside create_runner succeeds
        fake_ray_runner_mod = MagicMock()
        fake_ray_runner_mod.RayLoopRunner = mock_ray_runner_cls

        daemon_cfg, agent_cfg = _config(distributed=True, worker_pool_enabled=False)
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
    """Default SootheDaemonConfig has distributed.enabled=False and thread_pool.enabled=True."""

    def test_default_config_has_thread_pool_enabled(self) -> None:
        """Default config enables thread pool (ThreadLoopRunner)."""
        daemon_cfg = SootheDaemonConfig()
        agent_cfg = SootheConfig()
        assert daemon_cfg.distributed.enabled is False
        assert daemon_cfg.thread_pool.enabled is True
        assert daemon_cfg.worker_pool.enabled is False
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-default")
        assert isinstance(runner, ThreadLoopRunner)

    def test_explicit_worker_pool_returns_pool_runner(self) -> None:
        """Explicitly enabling worker pool and disabling thread pool returns PoolLoopRunner."""
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=True)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=False)
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-local")
        assert isinstance(runner, PoolLoopRunner)


class TestLoopRunnerFactoryIdentityValidation:
    """Identity + worker_pool mode is rejected at factory construction."""

    def test_raises_when_identity_enabled_with_worker_pool(self) -> None:
        from soothe.identity.runtime import IdentityConfig, IdentityRuntime

        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=True)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=False)
        daemon_cfg.identity = IdentityConfig(enabled=True)
        agent_cfg = SootheConfig()

        identity_runtime = IdentityRuntime(
            service=MagicMock(),
            config=daemon_cfg.identity,
        )

        with pytest.raises(ValueError, match="Identity service requires thread_pool mode"):
            LoopRunnerFactory(daemon_cfg, agent_cfg, identity_runtime=identity_runtime)


class TestLoopRunnerFactoryModeValidation:
    """Tests for validate_runner_mode() ensuring exactly one mode enabled."""

    def test_raises_value_error_when_no_mode_enabled(self) -> None:
        """When all modes disabled, validation fails."""
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=False)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=False)
        daemon_cfg.distributed = DistributedConfig(enabled=False)
        agent_cfg = SootheConfig()
        with pytest.raises(ValueError, match="No runner mode enabled"):
            LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_raises_value_error_when_multiple_modes_enabled(self) -> None:
        """When multiple modes enabled, validation fails."""
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=True)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=True)
        agent_cfg = SootheConfig()
        with pytest.raises(ValueError, match="Multiple runner modes enabled"):
            LoopRunnerFactory(daemon_cfg, agent_cfg)

    def test_worker_pool_valid_when_only_one_enabled(self) -> None:
        """Worker pool is valid when only it is enabled."""
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=True)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=False)
        daemon_cfg.distributed = DistributedConfig(enabled=False)
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-pool")
        assert isinstance(runner, PoolLoopRunner)

    def test_thread_pool_valid_when_only_one_enabled(self) -> None:
        """Thread pool is valid when only it is enabled (also default)."""
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=False)
        daemon_cfg.thread_pool = ThreadPoolConfig(enabled=True)
        daemon_cfg.distributed = DistributedConfig(enabled=False)
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-thread")
        assert isinstance(runner, ThreadLoopRunner)
