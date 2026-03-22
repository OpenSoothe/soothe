"""Thread executor for concurrent execution with isolation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from soothe.core.thread.rate_limiter import APIRateLimiter
from soothe.daemon.thread_logger import ThreadLogger

if TYPE_CHECKING:
    from soothe.core.runner import SootheRunner

logger = logging.getLogger(__name__)


class ThreadExecutor:
    """Manages concurrent thread execution with isolation."""

    def __init__(
        self,
        runner: SootheRunner,
        max_concurrent_threads: int = 4,
    ) -> None:
        """Initialize thread executor.

        Args:
            runner: SootheRunner instance
            max_concurrent_threads: Maximum concurrent threads
        """
        self._runner = runner
        self._max_concurrent = max_concurrent_threads
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._rate_limiter = APIRateLimiter()

    async def execute_thread(
        self,
        thread_id: str,
        user_input: str,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """Execute query in isolated thread context.

        Args:
            thread_id: Thread ID to execute in
            user_input: User input text
            **kwargs: Additional arguments for runner.astream

        Yields:
            Stream chunks from runner
        """
        # Set thread context
        self._runner.set_current_thread_id(thread_id)

        # Create isolated logger
        ThreadLogger(thread_id=thread_id)

        logger.info("Executing query in thread %s", thread_id)

        # Acquire rate limit permit
        async with self._rate_limiter.acquire():
            try:
                # Execute in isolated context
                async for chunk in self._runner.astream(
                    user_input,
                    thread_id=thread_id,
                    **kwargs,
                ):
                    # Log to thread-specific logger
                    # ThreadLogger will handle the actual logging
                    yield chunk
            except Exception as e:
                logger.error("Error in thread %s: %s", thread_id, e)
                raise
