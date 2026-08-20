# IG-754: Host prompts live in `soothe.prompts`

**Created**: 2026-08-20
**Status**: Implemented
**Package**: `soothe`
**Related**: nano `soothe_nano.prompts`

---

## Goal

`soothe.prompts` is the host prompt package: nano CoreAgent helpers are
re-exported from `__init__.py`; StrangeLoop envelopes, ledger projection,
graph wrappers, the Jinja loader, and host XML fragments are submodules of
the same package. `soothe.sloop.prompts` is removed.

## Design rules

1. Nano re-exports live only in `soothe.prompts.__init__.py` (no wrapper
   modules for identity / context XML / project instructions / system
   templates).
2. Host-owned implementation stays in named submodules
   (`user_message`, `graph_wrapper`, `plan_ledger_projection`, `loader`,
   `fragments`). Do-or-decompose copy is XML under `fragments/decompose/`;
   `soothe.prompts.__init__` re-exports it and selects the root vs child
   user hint.
3. CoreAgent already resolves system prompts from nano via
   `SootheConfig.resolve_system_prompt`; do not duplicate nano guide bodies
   on the host.

## Work items

- [x] Collapse nano wrappers into `soothe.prompts.__init__.py`
- [x] Move `soothe.sloop.prompts` into `soothe.prompts`
- [x] Update importers and hygiene tests
