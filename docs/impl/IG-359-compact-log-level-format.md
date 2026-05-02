# IG-359: Compact log level format

## Goal

Use single-letter level markers in default log formats (`D`, `I`, `W`, `E`, `C`) instead of full names (`DEBUG`, `INFO`, …).

Use compact `%(asctime)s` via `ShortLevelFormatter.formatTime`: `YYYYMMDDTHHMMSS.mmm` local time — same fields and millisecond resolution as the stock `YYYY-MM-DD HH:MM:SS,mmm`, shorter on the wire.

## Scope

- `soothe_sdk.utils.logging`: `ShortLevelFormatter`, default format strings
- `soothe.logging.setup`: file + console formatters
- Config defaults: `ConsoleLoggingConfig`, `packages/soothe/src/soothe/config/config.yml`

## Status

Implemented.
