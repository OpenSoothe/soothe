# IG-339: LangChain Community Requests toolkit integration

## Goal

Expose LangChain `RequestsToolkit` (`requests_get`, `requests_post`, `requests_patch`, `requests_put`, `requests_delete`) as Soothe tool group **`http_requests`**, configured via `tools.http_requests`.

## Security

- Defaults **`enabled: true`** and **`allow_dangerous_requests: true`** so the toolkit is active out of the box; disable in YAML when outbound HTTP must be blocked.
- LangChain tools raise unless **`allow_dangerous_requests=True`** on each tool; we only construct the toolkit when config opts in to both flags.
- Future hardening: optional URL policy / `OperationKind` for HTTP (see IG discussion).

## Status

Completed.
