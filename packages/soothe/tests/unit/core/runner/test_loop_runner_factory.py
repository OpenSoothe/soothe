"""Unit tests for LoopRunnerFactory (RFC-221).

Verifies correct runner type selection and Ray validation at construction time.
No real subprocesses or Ray cluster required.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig
from soothe.core.runner.factory import LoopRunnerFactory
from soothe.core.runner.local_runner import LocalLoopRunner
from soothe.core.runner.pool_runner import PoolLoopRunner


def _config(distributed: bool = False, worker_pool_enabled: bool = True) -> SootheConfig:
    """Create a config with specific distribution and pool settings."""
    cfg = SootheConfig()
    cfg.daemon.distributed.enabled = distributed
    cfg.daemon.worker_pool.enabled = worker_pool_enabled
    return cfg


class TestLoopRunnerFactoryPoolMode:
    """Factory creates PoolLoopRunner when worker_pool.enabled=True (default)."""

    def test_create_runner_returns_pool_runner_by_default(self) -> None:
        """By default, worker_pool.enabled=True, so PoolLoopRunner is used."""
        factory = LoopRunnerFactory(SootheConfig())
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, PoolLoopRunner)

    def test_create_runner_unique_per_loop_id(self) -> None:
        factory = LoopRunnerFactory(SootheConfig())
        r1 = factory.create_runner("loop-1")
        r2 = factory.create_runner("loop-2")
        assert r1 is not r2
        assert r1._loop_id == "loop-1"
        assert r2._loop_id == "loop-2"


class TestLoopRunnerFactoryLocalMode:
    """Factory creates LocalLoopRunner when worker_pool.enabled=False and distributed=False."""

    def test_create_runner_returns_local_runner_when_pool_disabled(self) -> None:
        """When pool disabled and distributed disabled, LocalLoopRunner is used."""
        factory = LoopRunnerFactory(_config(distributed=False, worker_pool_enabled=False))
        runner = factory.create_runner("loop-abc")
        assert isinstance(runner, LocalLoopRunner)

    def test_local_mode_does_not_import_ray(self) -> None:
        """Creating a factory or runner in local mode must not import Ray."""
        # Ensure ray is not in sys.modules at all after factory creation
        with patch.dict(sys.modules, {"ray": None}):
            factory = LoopRunnerFactory(_config(distributed=False, worker_pool_enabled=False))
            runner = factory.create_runner("loop-xyz")
        assert isinstance(runner, LocalLoopRunner)


class TestLoopRunnerFactoryDistributedMode:
    """Factory creates RayLoopRunner when distributed.enabled=True; fails fast if Ray absent."""

    def test_raises_import_error_when_ray_not_installed(self) -> None:
        """Construction must fail fast when Ray is unavailable in distributed mode."""
        with patch.dict(sys.modules, {"ray": None}):
            with pytest.raises(ImportError, match="Ray is required"):
                LoopRunnerFactory(_config(distributed=True, worker_pool_enabled=False))

    def test_create_runner_returns_ray_runner_when_ray_available(self) -> None:
        """create_runner() returns a RayLoopRunner when Ray is importable."""
        mock_ray = MagicMock()
        fake_runner_instance = MagicMock()
        mock_ray_runner_cls = MagicMock(return_value=fake_runner_instance)

        # Provide a fake ray_runner module so the lazy import inside create_runner succeeds
        fake_ray_runner_mod = MagicMock()
        fake_ray_runner_mod.RayLoopRunner = mock_ray_runner_cls

        with patch.dict(
            sys.modules,
            {
                "ray": mock_ray,
                "soothe.core.runner.ray_runner": fake_ray_runner_mod,
                "soothe.core.runner.ray_actor": MagicMock(),
            },
        ):
            factory = LoopRunnerFactory(_config(distributed=True, worker_pool_enabled=False))
            runner = factory.create_runner("loop-distributed")

        mock_ray_runner_cls.assert_called_once_with("loop-distributed", factory._config)
        assert runner is fake_runner_instance


class TestLoopRunnerFactoryDefaultConfig:
    """Default SootheConfig has distributed.enabled=False and worker_pool.enabled=True."""

    def test_default_config_has_pool_enabled(self) -> None:
        """Default config enables worker pool (PoolLoopRunner)."""
        cfg = SootheConfig()
        assert cfg.daemon.distributed.enabled is False
        assert cfg.daemon.worker_pool.enabled is True
        factory = LoopRunnerFactory(cfg)
        runner = factory.create_runner("loop-default")
        assert isinstance(runner, PoolLoopRunner)

    def test_explicit_local_mode_returns_local_runner(self) -> None:
        """Explicitly disabling pool returns LocalLoopRunner."""
        cfg = SootheConfig()
        cfg.daemon.worker_pool.enabled = False
        factory = LoopRunnerFactory(cfg)
        runner = factory.create_runner("loop-local")
        assert isinstance(runner, LocalLoopRunner)
