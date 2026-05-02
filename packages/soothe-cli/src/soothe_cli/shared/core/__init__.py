"""Core architecture for RFC-0019 unified event processing."""

from soothe_cli.shared.core.event_processor import EventProcessor
from soothe_cli.shared.core.presentation_engine import PresentationEngine
from soothe_cli.shared.core.processor_state import ProcessorState
from soothe_cli.shared.core.renderer_protocol import RendererProtocol

__all__ = [
    "EventProcessor",
    "RendererProtocol",
    "ProcessorState",
    "PresentationEngine",
]
