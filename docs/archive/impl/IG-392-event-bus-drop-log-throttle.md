# IG-392: EventBus NORMAL/HIGH drop log throttling

## Problem

When the session event queue backs up (slow consumer vs. streaming producer), each dropped NORMAL event logged a separate `WARNING`. Under load this produced thousands of log lines per second—often correlated with long LLM runs or timeouts, but **not caused by** timeout logic emitting extra events.

## Change

- `packages/soothe/src/soothe/daemon/event_bus.py`: Rate-limit WARNING/ERROR logs for NORMAL and HIGH priority drops to **one line per topic per 5 seconds**, with a short note that similar logs are suppressed.
- Use each subscriber queue’s real `maxsize` for capacity math (fixes misleading `80%` / overflow behavior for small queues in tests).
- Fast-path skip `put_nowait` when `qsize >= maxsize` for NORMAL/HIGH to avoid hot-path exceptions.

## Verification

`./scripts/verify_finally.sh`
