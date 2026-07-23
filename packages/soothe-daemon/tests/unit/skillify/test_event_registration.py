"""IG-643: skillify index events are registered in the shared REGISTRY."""

from soothe_sdk.core.registry import REGISTRY

from soothe_daemon.events.constants import (
    SKILLIFY_INDEX_FAILED,
    SKILLIFY_INDEX_STARTED,
    SKILLIFY_INDEX_UNCHANGED,
    SKILLIFY_INDEX_UPDATED,
    SKILLIFY_RETRIEVE_COMPLETED,
)
from soothe_daemon.skillify import events as skillify_events  # noqa: F401


def test_skillify_index_events_registered() -> None:
    for type_string in (
        SKILLIFY_RETRIEVE_COMPLETED,
        SKILLIFY_INDEX_STARTED,
        SKILLIFY_INDEX_UPDATED,
        SKILLIFY_INDEX_UNCHANGED,
        SKILLIFY_INDEX_FAILED,
    ):
        meta = REGISTRY.get_meta(type_string)
        assert meta is not None, f"{type_string} missing from REGISTRY"
