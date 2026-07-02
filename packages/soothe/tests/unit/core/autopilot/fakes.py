"""Shared AutopilotService test fakes (RFC-222 worker dispatch)."""

from __future__ import annotations


class IdleFakeRunner:
    """LoopRunnerProtocol stub that yields nothing (scheduling-only tests)."""

    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id
        self.cancel_called = False
        self.last_request = None

    async def run(self, request):  # noqa: ANN001
        self.last_request = request
        yield None

    async def cancel(self) -> None:
        self.cancel_called = True


class IdleFakeFactory:
    """Minimal runner factory for AutopilotService unit tests."""

    def __init__(self) -> None:
        self.created: list[str] = []

    def create_runner(self, loop_id: str):  # noqa: ANN001
        self.created.append(loop_id)
        return IdleFakeRunner(loop_id)
