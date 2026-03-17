"""Extended Serper search tool with multi-type search support.

Ported from noesium's serper toolkit. langchain's GoogleSerperAPIWrapper only
supports basic web search; this adds image, news, scholar, maps, video, places,
autocomplete, and Google Lens.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.utils.tool_error_handler import tool_error_handler

SERPER_BASE_URL = "https://google.serper.dev"


class SerperSearchTool(BaseTool):
    """Multi-type search via the Serper API.

    Supports: search, images, news, scholar, maps, videos, autocomplete, lens, places.
    """

    name: str = "serper_search"
    description: str = (
        "Search the web using Google via Serper API. Supports multiple search types: "
        "'search' (web), 'images', 'news', 'scholar', 'maps', 'videos', 'autocomplete', "
        "'lens' (visual search by image URL), 'places'. "
        "Provide `query` and optionally `search_type` (default: 'search'), "
        "`num` (default: 10), `gl` (country), `hl` (language)."
    )
    api_key: str = Field(default="")

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Serper search tool.

        Args:
            **kwargs: Pydantic model fields. Falls back to SERPER_API_KEY env var.
        """
        if not kwargs.get("api_key"):
            kwargs["api_key"] = os.environ.get("SERPER_API_KEY", "")
        super().__init__(**kwargs)

    @tool_error_handler("serper_search", return_type="dict")
    def _make_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        import requests

        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        resp = requests.post(
            f"{SERPER_BASE_URL}/{endpoint}",
            json=payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _run(
        self,
        query: str,
        search_type: str = "search",
        num: int = 10,
        gl: str | None = None,
        hl: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"q": query, "num": num}
        if gl:
            payload["gl"] = gl
        if hl:
            payload["hl"] = hl

        endpoint_map = {
            "search": "search",
            "images": "images",
            "news": "news",
            "scholar": "scholar",
            "maps": "maps",
            "videos": "videos",
            "autocomplete": "autocomplete",
            "lens": "lens",
            "places": "places",
        }
        endpoint = endpoint_map.get(search_type, "search")

        if search_type == "lens":
            payload = {"url": query, "num": num}
            if gl:
                payload["gl"] = gl
            if hl:
                payload["hl"] = hl

        return self._make_request(endpoint, payload)

    @tool_error_handler("serper_search", return_type="dict")
    async def _arun(
        self,
        query: str,
        search_type: str = "search",
        num: int = 10,
        gl: str | None = None,
        hl: str | None = None,
    ) -> dict[str, Any]:
        import aiohttp

        payload: dict[str, Any] = {"q": query, "num": num}
        if gl:
            payload["gl"] = gl
        if hl:
            payload["hl"] = hl

        endpoint_map = {
            "search": "search",
            "images": "images",
            "news": "news",
            "scholar": "scholar",
            "maps": "maps",
            "videos": "videos",
            "autocomplete": "autocomplete",
            "lens": "lens",
            "places": "places",
        }
        endpoint = endpoint_map.get(search_type, "search")

        if search_type == "lens":
            payload = {"url": query, "num": num}
            if gl:
                payload["gl"] = gl
            if hl:
                payload["hl"] = hl

        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{SERPER_BASE_URL}/{endpoint}",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp,
        ):
            resp.raise_for_status()
            return await resp.json()


def create_serper_tools() -> list[BaseTool]:
    """Create extended Serper search tools.

    Returns:
        List containing the `SerperSearchTool`.
    """
    return [SerperSearchTool()]
