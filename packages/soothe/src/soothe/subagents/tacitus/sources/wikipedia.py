"""Wikipedia encyclopedia capability."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from soothe.subagents.tacitus.json_util import compact_search_query
from soothe.subagents.tacitus.protocol import CapabilityId, GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_USER_AGENT = "Soothe/1.0 (https://github.com/OpenSoothe/soothe; research)"
_CAPABILITY_DESCRIPTION = (
    "Encyclopedia articles, definitions, historical overviews, biographies, "
    "and conceptual background from Wikipedia."
)


def _wiki_lang(query: str) -> str:
    return "zh" if any("\u4e00" <= c <= "\u9fff" for c in query) else "en"


class WikipediaSource:
    """Wikipedia via package, MediaWiki API, then langchain fallback."""

    capability_id: CapabilityId = "wikipedia"
    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self) -> None:
        self._langchain_tool: object | None = None
        self._langchain_tried = False

    def _ensure_langchain(self) -> None:
        if self._langchain_tried:
            return
        self._langchain_tried = True
        try:
            from langchain_community.tools.wikipedia.tool import WikipediaQueryRun
            from langchain_community.utilities import WikipediaAPIWrapper

            self._langchain_tool = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        except Exception:
            logger.warning(
                "[Wikipedia] LangChain fallback not available",
                exc_info=True,
            )

    @staticmethod
    def _query_wikipedia_package(query: str) -> str | None:
        try:
            import wikipedia

            wikipedia.set_lang(_wiki_lang(query))
            return wikipedia.summary(query, sentences=8, auto_suggest=True)
        except Exception:
            return None

    @staticmethod
    def _query_mediawiki_api(query: str) -> str | None:
        """Fetch intro extract via MediaWiki API (no ``wikipedia`` package dependency)."""
        lang = _wiki_lang(query)
        base = f"https://{lang}.wikipedia.org/w/api.php"

        def _get(params: dict[str, str | int]) -> dict[str, object]:
            url = base + "?" + urllib.parse.urlencode({**params, "format": "json"})
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())

        try:
            search = _get({"action": "opensearch", "search": query, "limit": 3})
            titles = search[1] if isinstance(search, list) and len(search) > 1 else []
            if not titles or not isinstance(titles, list):
                return None
            title = str(titles[0])
            data = _get(
                {
                    "action": "query",
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "titles": title,
                }
            )
            pages = data.get("query", {})
            if not isinstance(pages, dict):
                return None
            page_map = pages.get("pages", {})
            if not isinstance(page_map, dict) or not page_map:
                return None
            page = next(iter(page_map.values()))
            if not isinstance(page, dict):
                return None
            extract = page.get("extract")
            if isinstance(extract, str) and extract.strip():
                return extract.strip()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                logger.info("[Wikipedia] query=%r status=rate_limited backend=api", query)
            else:
                logger.debug(
                    "[Wikipedia] query=%r status=http_error backend=api code=%s",
                    query,
                    exc.code,
                )
        except Exception:
            logger.debug(
                "[Wikipedia] query=%r status=exception backend=api",
                query,
                exc_info=True,
            )
        return None

    async def _query_langchain(self, query: str) -> str | None:
        if self._langchain_tool is None:
            return None
        try:
            run = getattr(self._langchain_tool, "run", None)
            if callable(run):
                return await asyncio.to_thread(run, query)
            arun = getattr(self._langchain_tool, "_arun", None)
            if callable(arun):
                return await arun(query)  # type: ignore[misc]
        except json.JSONDecodeError:
            logger.debug(
                "[Wikipedia] query=%r status=decode_error backend=langchain",
                query,
            )
        except Exception:
            logger.debug(
                "[Wikipedia] query=%r status=exception backend=langchain",
                query,
                exc_info=True,
            )
        return None

    @property
    def name(self) -> str:
        return "wikipedia"

    @property
    def source_type(self) -> SourceType:
        return "encyclopedia"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        search_q = compact_search_query(query, max_len=80)
        logger.info("[Wikipedia] query=%r status=start", search_q)

        for backend, fetch in (
            ("package", self._query_wikipedia_package),
            ("api", self._query_mediawiki_api),
        ):
            raw = fetch(search_q)
            if raw:
                logger.info(
                    "[Wikipedia] query=%r status=success backend=%s output_chars=%d",
                    search_q,
                    backend,
                    len(raw),
                )
                return [
                    SourceResult(
                        content=raw[:3000],
                        source_ref="wikipedia",
                        source_name="wikipedia",
                        metadata={"sub_source": f"wikipedia_{backend}"},
                    )
                ]

        self._ensure_langchain()
        lc_raw = await self._query_langchain(search_q)
        if lc_raw and "No good" not in lc_raw:
            text = str(lc_raw)
            logger.info(
                "[Wikipedia] query=%r status=success backend=langchain output_chars=%d",
                search_q,
                len(text),
            )
            return [
                SourceResult(
                    content=text[:3000],
                    source_ref="wikipedia",
                    source_name="wikipedia",
                    metadata={"sub_source": "wikipedia_langchain"},
                )
            ]

        if self._langchain_tool is None:
            logger.info(
                "[Wikipedia] query=%r status=skipped reason=langchain_unavailable",
                search_q,
            )

        logger.info("[Wikipedia] query=%r status=no_results", search_q)
        return []
