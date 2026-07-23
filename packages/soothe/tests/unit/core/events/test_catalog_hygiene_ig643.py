"""IG-643: host no longer exports dead loop/checkpoint event consts."""

import soothe.events as events


def test_dead_host_event_consts_removed() -> None:
    for name in (
        "CHECKPOINT_ANCHOR_CREATED",
        "LOOP_DETACHED",
        "LOOP_REATTACHED",
    ):
        assert name not in events.__all__
        assert not hasattr(events, name)


def test_nano_primitives_registered_without_host_rereg() -> None:
    from soothe_sdk.core.events import ERROR, MEMORY_RECALLED, STREAM_END
    from soothe_sdk.core.registry import REGISTRY

    import soothe.events  # noqa: F401

    for type_string in (STREAM_END, MEMORY_RECALLED, ERROR):
        assert REGISTRY.get_meta(type_string) is not None
