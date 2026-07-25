"""Public soothe host diagnose API for soothed doctor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from soothe.config import SootheConfig
from soothe.diagnose.models import CategoryResult

VITAL_CATEGORIES: list[str] = ["host"]
DEEP_CATEGORIES: list[str] = []
ALL_CATEGORIES: list[str] = [*VITAL_CATEGORIES, *DEEP_CATEGORIES]


async def diagnose(
    config: SootheConfig | None = None,
    *,
    deep: bool = False,  # noqa: ARG001 — reserved for future host deep checks
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run host-owned diagnose categories and return dict-contract results.

    Args:
        config: Host ``SootheConfig`` (optional).
        deep: Reserved for future deep host categories.
        categories: Explicit category filter (subset of host categories).

    Returns:
        List of category dicts matching ``CategoryResult.to_dict()``.
    """
    from soothe.diagnose.host import check_host

    check_methods: dict[str, Callable[[], Awaitable[CategoryResult]]] = {
        "host": lambda: check_host(config),
    }

    if categories is not None:
        selected = [c for c in categories if c in check_methods]
    else:
        selected = list(VITAL_CATEGORIES)

    results: list[dict[str, Any]] = []
    for name in selected:
        result = await check_methods[name]()
        results.append(result.to_dict())
    return results
