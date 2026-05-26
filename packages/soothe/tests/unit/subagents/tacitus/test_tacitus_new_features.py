"""Unit tests for Tacitus new features (IG-432)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.subagents.tacitus.events import (
    TacitusProgressEvent,
)
from soothe.subagents.tacitus.protocol import TacitusConfig


class TestTacitusConfigOptions:
    """Tests for new config options."""

    def test_default_source_timeout(self):
        """Default source timeout should be 10s."""
        config = TacitusConfig()
        assert config.source_timeout_sec == 10.0

    def test_default_parallel_sources_enabled(self):
        """Parallel sources should be enabled by default."""
        config = TacitusConfig()
        assert config.enable_parallel_sources is True

    def test_default_early_termination_enabled(self):
        """Early termination should be enabled by default."""
        config = TacitusConfig()
        assert config.enable_early_termination is True

    def test_default_min_results_for_termination(self):
        """Default min results for termination should be 3."""
        config = TacitusConfig()
        assert config.min_results_for_termination == 3

    def test_default_min_source_diversity(self):
        """Default min source diversity should be 2."""
        config = TacitusConfig()
        assert config.min_source_diversity == 2

    def test_default_llm_timeout(self):
        """Default LLM timeout should be 30s."""
        config = TacitusConfig()
        assert config.llm_timeout_sec == 30.0

    def test_default_synthesis_role_is_fast(self):
        """Default synthesis role should be fast."""
        config = TacitusConfig()
        assert config.synthesis_role == "fast"

    def test_config_bounds_validation(self):
        """Config values should respect bounds."""
        # Test bounds
        config = TacitusConfig(
            source_timeout_sec=5.0,
            llm_timeout_sec=15.0,
            min_results_for_termination=5,
            min_source_diversity=3,
        )
        assert config.source_timeout_sec == 5.0
        assert config.llm_timeout_sec == 15.0
        assert config.min_results_for_termination == 5
        assert config.min_source_diversity == 3

    def test_default_polite_concurrency_enabled(self):
        """Polite concurrency should be enabled by default."""
        config = TacitusConfig()
        assert config.enable_polite_concurrency is True

    def test_default_polite_rate_limit_rps(self):
        """Default rate limit RPS should be 1.0."""
        config = TacitusConfig()
        assert config.polite_rate_limit_rps == 1.0

    def test_default_polite_burst_size(self):
        """Default burst size should be 3."""
        config = TacitusConfig()
        assert config.polite_burst_size == 3

    def test_default_polite_max_concurrent(self):
        """Default max concurrent should be 5."""
        config = TacitusConfig()
        assert config.polite_max_concurrent == 5

    def test_default_polite_retry_max(self):
        """Default retry max should be 3."""
        config = TacitusConfig()
        assert config.polite_retry_max == 3

    def test_default_polite_retry_base_delay(self):
        """Default retry base delay should be 1.0."""
        config = TacitusConfig()
        assert config.polite_retry_base_delay == 1.0

    def test_default_polite_circuit_breaker_threshold(self):
        """Default circuit breaker threshold should be 5."""
        config = TacitusConfig()
        assert config.polite_circuit_breaker_threshold == 5

    def test_default_polite_circuit_breaker_reset_sec(self):
        """Default circuit breaker reset time should be 60.0."""
        config = TacitusConfig()
        assert config.polite_circuit_breaker_reset_sec == 60.0

    def test_default_polite_domain_overrides(self):
        """Default domain overrides should be empty dict."""
        config = TacitusConfig()
        assert config.polite_domain_overrides == {}

    def test_polite_config_with_overrides(self):
        """Polite config should accept custom values."""
        config = TacitusConfig(
            enable_polite_concurrency=False,
            polite_rate_limit_rps=2.5,
            polite_burst_size=5,
            polite_max_concurrent=8,
            polite_retry_max=5,
            polite_retry_base_delay=0.5,
            polite_circuit_breaker_threshold=3,
            polite_circuit_breaker_reset_sec=30.0,
            polite_domain_overrides={
                "api.example.com": {"rps": 5.0, "burst": 10, "concurrent": 10},
            },
        )
        assert config.enable_polite_concurrency is False
        assert config.polite_rate_limit_rps == 2.5
        assert config.polite_burst_size == 5
        assert config.polite_max_concurrent == 8
        assert config.polite_retry_max == 5
        assert config.polite_retry_base_delay == 0.5
        assert config.polite_circuit_breaker_threshold == 3
        assert config.polite_circuit_breaker_reset_sec == 30.0
        assert config.polite_domain_overrides["api.example.com"]["rps"] == 5.0


class TestTacitusProgressEvent:
    """Tests for progress events."""

    def test_progress_event_creation(self):
        """Progress event should be created with all fields."""
        event = TacitusProgressEvent(
            phase="gather",
            message="Gathering from 3 sources...",
            loop_count=1,
            total_loops=3,
            sources_completed=0,
            total_sources=3,
        )
        assert event.phase == "gather"
        assert event.loop_count == 1
        assert event.total_loops == 3
        assert event.total_sources == 3

    def test_progress_event_defaults(self):
        """Progress event should have sensible defaults."""
        event = TacitusProgressEvent(
            phase="analyze",
            message="Analyzing...",
        )
        assert event.loop_count == 0
        assert event.total_loops == 0
        assert event.sources_completed == 0
        assert event.total_sources == 0

    def test_progress_event_to_dict(self):
        """Progress event should convert to dict for wire transmission."""
        event = TacitusProgressEvent(
            phase="synthesize",
            message="Synthesizing...",
            loop_count=2,
            total_loops=3,
        )
        data = event.to_dict()
        assert data["type"] == "soothe.subagent.tacitus.progress"
        assert data["phase"] == "synthesize"
        assert data["loop_count"] == 2


class TestLLMTimeoutHelpers:
    """Tests for LLM timeout helper functions."""

    @pytest.mark.asyncio
    async def test_invoke_llm_with_timeout_success(self):
        """LLM invocation should succeed within timeout."""
        from soothe.subagents.tacitus.engine import _invoke_llm_with_timeout

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=MagicMock(content="test response"))

        result = await _invoke_llm_with_timeout(
            mock_model,
            [{"role": "user", "content": "test"}],
            timeout_sec=1.0,
            node_name="test",
        )

        assert result.content == "test response"
        mock_model.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_llm_with_timeout_raises_on_slow_response(self):
        """LLM invocation should raise TimeoutError on slow response."""
        from soothe.subagents.tacitus.engine import _invoke_llm_with_timeout

        async def slow_response(*_args, **_kwargs):
            await asyncio.sleep(0.1)
            return MagicMock(content="too slow")

        mock_model = MagicMock()
        mock_model.ainvoke = slow_response

        with pytest.raises(TimeoutError):
            await _invoke_llm_with_timeout(
                mock_model,
                [{"role": "user", "content": "test"}],
                timeout_sec=0.01,  # Very short timeout
                node_name="test",
            )


class TestIntegration:
    """Integration tests for new features."""

    def test_config_with_all_latency_options(self):
        """Config should support all latency control options together."""
        config = TacitusConfig(
            source_timeout_sec=15.0,
            enable_parallel_sources=True,
            enable_early_termination=True,
            min_results_for_termination=5,
            min_source_diversity=3,
            llm_timeout_sec=45.0,
            synthesis_role="fast",
        )

        assert config.source_timeout_sec == 15.0
        assert config.enable_parallel_sources is True
        assert config.enable_early_termination is True
        assert config.min_results_for_termination == 5
        assert config.min_source_diversity == 3
        assert config.llm_timeout_sec == 45.0
        assert config.synthesis_role == "fast"
