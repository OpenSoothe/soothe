"""Token display helper mixin (inherited by SootheApp via MRO).

Command handling was moved to ``_ExecutionMixin``; this mixin retains only
``_get_conversation_token_count`` which is called from there.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class _CommandsMixin:
    """Token display helper inherited by SootheApp via MRO."""

    async def _get_conversation_token_count(self) -> int | None:
        """Return the approximate conversation-only token count.

        Returns:
            Token count as an integer, or `None` if state is unavailable.
        """
        if not self._lc_loop_id:
            return None
        try:
            from langchain_core.messages import messages_from_dict
            from langchain_core.messages.utils import count_tokens_approximately

            if self._daemon_session is None:
                return None
            snap = await self._daemon_session.aget_loop_state(self._lc_loop_id)
            vals = getattr(snap, "values", None)
            if not isinstance(vals, dict):
                return None
            raw = vals.get("messages")
            if not isinstance(raw, list) or not raw:
                return None
            if isinstance(raw[0], dict):
                messages = messages_from_dict(raw)
            else:
                messages = raw

            return count_tokens_approximately(messages)
        except Exception:  # best-effort for /tokens display
            logger.debug("Failed to retrieve conversation token count", exc_info=True)
            return None
