"""Plugin-side event registration (IG-175: Community plugin SDK decoupling).

Provides a lightweight event registration mechanism for plugin authors
without requiring the full daemon runtime. Events registered here are
stored in a module-level dict that the daemon reads during plugin loading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soothe_sdk.events import SootheEvent
from soothe_sdk.verbosity import VerbosityTier


@dataclass(frozen=True)
class PluginEventMeta:
    """Metadata for a plugin-registered event type.

    This is a simplified version of the daemon's EventMeta, containing
    only what plugin authors need to provide.

    Args:
        type_string: The event type identifier (e.g., "soothe.plugin.myevent").
        model: The Pydantic event class (must inherit from SootheEvent).
        verbosity: Default verbosity tier for this event.
        summary_template: Template string for event summaries.
    """

    type_string: str
    model: type[SootheEvent]
    verbosity: VerbosityTier
    summary_template: str = ""


# Module-level registry for plugin events
_PLUGIN_EVENTS: dict[str, PluginEventMeta] = {}


def register_event(
    event_class: type[SootheEvent],
    verbosity: VerbosityTier | str | None = None,
    summary_template: str = "",
) -> None:
    """Register a custom event type for a plugin.

    This function stores event metadata in a module-level dict that
    the daemon's plugin loader reads during initialization. The daemon
    then merges these events into its own global EventRegistry.

    Plugin authors call this at module import time to register their
    custom events:

    ```python
    from soothe_sdk import register_event, SubagentEvent, VerbosityTier


    class MyCustomEvent(SubagentEvent):
        type: str = "soothe.plugin.myplugin.custom"
        data: str


    register_event(MyCustomEvent, verbosity=VerbosityTier.NORMAL, summary_template="Custom: {data}")
    ```

    Args:
        event_class: The Pydantic event model class (must have a `type` field with default).
        verbosity: Verbosity tier for this event (VerbosityTier or string like "normal").
        summary_template: Template for event summaries (use {field} placeholders).

    Raises:
        ValueError: If event_class doesn't have a `type` field with default value.
    """
    # Extract type string from the model's `type` field default
    if not hasattr(event_class, "type"):
        raise ValueError(f"Event class {event_class.__name__} must have a 'type' field")

    # Get the default value of the type field
    type_field = event_class.model_fields.get("type")
    if type_field is None or type_field.default is None:
        raise ValueError(
            f"Event class {event_class.__name__} must have a 'type' field with a default value"
        )

    type_string = type_field.default

    # Normalize verbosity to VerbosityTier
    if verbosity is None:
        verbosity_tier = VerbosityTier.NORMAL
    elif isinstance(verbosity, str):
        # Map string verbosity names to VerbosityTier
        verbosity_map = {
            "quiet": VerbosityTier.QUIET,
            "normal": VerbosityTier.NORMAL,
            "detailed": VerbosityTier.DETAILED,
            "debug": VerbosityTier.DEBUG,
            "internal": VerbosityTier.INTERNAL,
        }
        verbosity_tier = verbosity_map.get(verbosity.lower(), VerbosityTier.NORMAL)
    else:
        verbosity_tier = verbosity

    # Store in module-level dict
    _PLUGIN_EVENTS[type_string] = PluginEventMeta(
        type_string=type_string,
        model=event_class,
        verbosity=verbosity_tier,
        summary_template=summary_template,
    )


def get_plugin_events() -> dict[str, PluginEventMeta]:
    """Get all plugin-registered events.

    Called by the daemon's plugin loader to retrieve event metadata
    and merge into the daemon's EventRegistry.

    Returns:
        Dict mapping event type strings to PluginEventMeta instances.
    """
    return _PLUGIN_EVENTS.copy()


def clear_plugin_events() -> None:
    """Clear all plugin-registered events.

    Used during testing or when unloading plugins.
    """
    _PLUGIN_EVENTS.clear()
