# IG-696: Migrate wizsearch toolkit to tarzi 0.2.3

## Goal

Replace the `wizsearch` package dependency with direct `tarzi>=0.2.3` calls for
`wizsearch_search` / `wizsearch_crawl`, without breaking config keys or tool
names.

## Scope

| Area | Change |
|------|--------|
| Dep | `soothe-nano`: drop `wizsearch`; add `tarzi>=0.2.3,<0.3.0` |
| Impl | `_internal/wizsearch.py` → `SearchEngine` + `WebFetcher` |
| Config | Keep `tools.wizsearch`; document failover semantics |
| Tests | Unit mocks target tarzi helpers; integration skips on `tarzi` |
| Docs | Wiki tools / yaml-reference; changelogs |

## Out of scope

- Renaming tools to `tarzi_*` or config key to `tools.tarzi`
- Absorbing wizsearch source into the tarzi repo
- Changing deep_research Tavily/DDG fallbacks

## Design notes

- Engines list → comma-separated ordered failover (`engine = "a,b,c"`).
- Aliases: `serper`→`google_serper`, `google_ai`→`googleai`, `wechat`→`sogou_weixin`.
- Crawl: `WebFetcher.fetch` / `fetch_with_proxy` (plain HTTP → browser cascade).
- Blocking native calls run via `asyncio.to_thread` (GIL released in tarzi).

## Checklist

- [x] Rewrite internal search/crawl helpers
- [x] Update pyproject + tests + wiki
- [x] `uv lock` refresh (nano + monorepo)
- [x] `./scripts/verify_finally.sh` green
