"""Jina Reader tool for extracting clean web content.

Ported from noesium's jina_research toolkit. No langchain equivalent exists.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

JINA_READER_BASE = "https://r.jina.ai"


class JinaReaderTool(BaseTool):
    """Extract clean, readable content from a URL via the Jina Reader API."""

    name: str = "jina_get_web_content"
    description: str = (
        "Extract clean, readable content from a web page URL. "
        "Returns the main text content stripped of navigation, ads, and boilerplate. "
        "Useful for reading articles, documentation, and web pages."
    )
    api_key: str = Field(default="")

    def __init__(self, **kwargs: Any) -> None:
        if not kwargs.get("api_key"):
            kwargs["api_key"] = os.environ.get("JINA_API_KEY", "")
        super().__init__(**kwargs)

    def _run(self, url: str) -> str:
        import requests

        headers: dict[str, str] = {"Accept": "text/plain"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        resp = requests.get(f"{JINA_READER_BASE}/{url}", headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.text

    async def _arun(self, url: str) -> str:
        import aiohttp

        headers: dict[str, str] = {"Accept": "text/plain"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with (
            aiohttp.ClientSession() as session,
            session.get(f"{JINA_READER_BASE}/{url}", headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp,
        ):
            resp.raise_for_status()
            return await resp.text()


def create_jina_tools() -> list[BaseTool]:
    """Create Jina Reader tools.

    Returns:
        List containing the `JinaReaderTool`.
    """
    return [JinaReaderTool()]
