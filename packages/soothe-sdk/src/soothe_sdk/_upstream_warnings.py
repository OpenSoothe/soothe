"""Central place to filter known noisy upstream warnings."""

from __future__ import annotations

import warnings


def register_upstream_warning_filters() -> None:
    """Register ``warnings`` filters for third-party import-time noise.

    LangGraph's checkpoint serde loads ``langgraph.checkpoint.serde.jsonplus``,
    which constructs a module-level ``langchain_core.load.load.Reviver()`` without
    an explicit ``allowed_objects`` argument. LangChain 1.3.3+ emits a pending
    deprecation (often attributed to ``encrypted.py`` because that module imports
    ``JsonPlusSerializer`` from ``jsonplus``). :func:`soothe_sdk.utils.serde.create_soothe_serde`
    configures msgpack allowlisting only; it does not affect that global reviver.
    """
    try:
        from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
    except ImportError:
        return

    warnings.filterwarnings(
        "ignore",
        category=LangChainPendingDeprecationWarning,
        message=(
            r"The default value of `allowed_objects` will change in a future version\. "
            r"Pass an explicit value .*"
        ),
    )


register_upstream_warning_filters()
