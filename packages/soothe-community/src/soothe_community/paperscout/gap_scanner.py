"""Gap Scanner: detects and fills missing notification slots.

Detects dates within a window where notifications were not sent
and triggers PaperScout to fill those gaps.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.backends.persistence import PersistStore
    from soothe_community.paperscout.state import PaperScoutConfig

logger = logging.getLogger(__name__)


class GapScanner:
    """Detects and fills missing recommendation slots.

    Scans a time window for dates where no notifications were sent
    and triggers PaperScout agent to process those dates.
    """

    def __init__(
        self,
        store: PersistStore,
        user_id: str,
        big_bang: date | None = None,
    ):
        """Initialize gap scanner.

        Args:
            store: PersistStore for notification records.
            user_id: User identifier for storage keys.
            big_bang: Earliest valid notification date (optional).
        """
        self._store = store
        self._user_id = user_id
        self._big_bang = big_bang

    def scan(self, window_days: int = 7) -> list[date]:
        """Find dates with missing notifications within the window.

        Args:
            window_days: Number of days to look back.

        Returns:
            List of dates missing notifications, respecting big_bang.
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=window_days)

        # Get all dates in the window
        all_dates = []
        current_date = start_date
        while current_date <= end_date:
            all_dates.append(current_date)
            current_date += timedelta(days=1)

        # Check which dates have notifications
        missing = []
        for check_date in all_dates:
            key = f"paperscout:notifications:{self._user_id}:{check_date.isoformat()}"
            record = self._store.get(key)
            if not record:
                missing.append(check_date)

        # Filter by big_bang if set
        if self._big_bang:
            missing = [d for d in missing if d >= self._big_bang]

        logger.info(f"Found {len(missing)} missing notification dates")
        return missing

    async def fill_gaps(
        self,
        config: PaperScoutConfig,
        agent: Any,  # PaperScoutAgent (avoid circular import)
    ) -> dict[date, str]:
        """Fill gaps by running PaperScout for each missing date.

        Args:
            config: PaperScout configuration.
            agent: PaperScout agent instance.

        Returns:
            Dict mapping dates to status strings.
        """
        missing = self.scan(config.gap_window_days)
        results: dict[date, str] = {}

        if not missing:
            logger.info("No gaps found")
            return results

        logger.info(f"Filling {len(missing)} gap(s): {[d.isoformat() for d in missing]}")

        for gap_date in sorted(missing):
            logger.info(f"Filling gap for {gap_date.isoformat()}...")

            # Create config for this specific date
            gap_config = config.model_copy(
                update={
                    "lookback_days": 1,  # Just this day
                }
            )

            try:
                # Run agent for this date
                # Note: Agent would need to support date range override
                result = await agent.run(config=gap_config, target_date=gap_date)
                status = "success" if result.get("success") else "failed"
                results[gap_date] = status
                logger.info(f"Gap fill for {gap_date}: {status}")
            except Exception as e:
                results[gap_date] = f"error: {e}"
                logger.error(f"Gap fill for {gap_date} failed: {e}")

        return results


__all__ = ["GapScanner"]
