"""Unit tests for LoopRunnerFactory (RFC-221).

Verifies correct runner type selection and Ray validation at construction time.
No real subprocesses or Ray cluster required.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from soothe.config import SootheConfig
from soothe.core.runner.local_runner import LocalLoopRunner

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import DistributedConfig, WorkerPoolConfig
from soothe_daemon.runner.factory import LoopRunnerFactory
from soothe_daemon.runner.pool_runner import PoolLoopRunner


def _config(
    distributed: bool = False, worker_pool_enabled: bool = True
) -> tuple[SootheDaemonConfig, SootheConfig]:
    """Create daemon and agent configs with specific distribution and pool settings."""
    daemon_cfg = SootheDaemonConfig()
    daemon_cfg.distributed = DistributedConfig(enabled=distributed)
    daemon_cfg.worker_pool = WorkerPoolConfig(enabled=worker_pool_enabled)
    agent_cfg = SootheConfig()
    return daemon_cfg, agent_cfg


class TestLoopRunnerFactoryPoolMode:
    """Factory creates PoolLoopRunner when worker_pool.enabled=True (default)."""

    def test_create_runner_returns_pool_runner_by_default(self) -> None:
        """By default, worker_pool.enabled=True, so PoolLoopRunner is used."""
        daemon_cfg = SootheDaemonConfig()
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, PoolLoopRunner)

    def test_create_runner_unique_per_loop_id(self) -> None:
        daemon_cfg = SootheDaemonConfig()
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        r1 = factory.create_runner("loop-1")
        r2 = factory.create_runner("loop-2")
        assert r1 is not r2
        assert r1._loop_id == "loop-1"
        assert r2._loop_id == "loop-2"


class TestLoopRunnerFactoryLocalMode:
    """Factory creates LocalLoopRunner when worker_pool.enabled=False and distributed=False."""

    def test_create_runner_returns_local_runner_when_pool_disabled(self) -> None:
        """When pool disabled and distributed disabled, LocalLoopRunner is used."""
        daemon_cfg, agent_cfg = _config(distributed=False, worker_pool_enabled=False)
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, LocalLoopRunner)

    def test_local_mode_does_not_import_ray(self) -> None:
        """Creating a factory or runner in local mode must not import Ray."""
        # Ensure ray is not in sys.modules at all after factory creation
        daemon_cfg, agent_cfg = _config(distributed=False, worker_pool_enabled=False)
        with patch.dict(sys.modules, {"ray": None}):
            factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
            runner = factory.create_runner("loop-xyz")
        assert isinstance(runner, LocalLoopRunner)


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
    """Default SootheDaemonConfig has distributed.enabled=False and worker_pool.enabled=True."""

    def test_default_config_has_pool_enabled(self) -> None:
        """Default config enables worker pool (PoolLoopRunner)."""
        daemon_cfg = SootheDaemonConfig()
        agent_cfg = SootheConfig()
        assert daemon_cfg.distributed.enabled is False
        assert daemon_cfg.worker_pool.enabled is True
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-default")
        assert isinstance(runner, PoolLoopRunner)

    def test_explicit_local_mode_returns_local_runner(self) -> None:
        """Explicitly disabling pool returns LocalLoopRunner."""
        daemon_cfg = SootheDaemonConfig()
        daemon_cfg.worker_pool = WorkerPoolConfig(enabled=False)
        agent_cfg = SootheConfig()
        factory = LoopRunnerFactory(daemon_cfg, agent_cfg)
        runner = factory.create_runner("loop-local")
        assert isinstance(runner, LocalLoopRunner)
