# Soothe Development Guide

> **Binding conduct for all agents and human contributors.** Compliance is mandatory; deviations require operator approval.

**Soothe** — a goal-driven orchestration framework for 24/7 autonomous agents. Extends `deepagents` with durable planning, reentrant loop state, and remote agent interop across a one-way monorepo dependency DAG.

**Read the rules files below before any non-trivial change.** Substantial work requires a design doc; minor changes follow commit/PR context. Run `./scripts/verify_finally.sh` before every commit. When in doubt, stop and ask.

---

## ⚠️ Critical Rules

| # | Rule | File |
|---|------|------|
| 1 | Design Docs | [development-process.md](.agents/rules/development-process.md) |
| 2 | Config Sync | [development-process.md](.agents/rules/development-process.md) |
| 3 | Ecosystem First | [development-process.md](.agents/rules/development-process.md) |
| 4 | Test Location | [development-process.md](.agents/rules/development-process.md) |
| 5 | Verification Required | [development-process.md](.agents/rules/development-process.md) |
| 6 | After Code Impl: Cleanse → Verify → Fix (MUST) | [development-process.md](.agents/rules/development-process.md) |
| 7 | Terminology | [code-style.md](.agents/rules/code-style.md) |
| 7b | Package Boundaries (MUST) | [package-boundaries.md](.agents/rules/package-boundaries.md) |
| 8 | DO NOT Cheat Tests | [development-process.md](.agents/rules/development-process.md) |
| 9 | No Keyword Heuristics | [code-style.md](.agents/rules/code-style.md) |
| 10 | Unified Persistence Backend (MUST) | [persistence-and-loops.md](.agents/rules/persistence-and-loops.md) |
| 11 | No AI Co-Authors (MUST) | [release-and-governance.md](.agents/rules/release-and-governance.md) |
| 12 | Drift Governance (MUST) | [release-and-governance.md](.agents/rules/release-and-governance.md) |
| 13 | Changelog (MUST) | [release-and-governance.md](.agents/rules/release-and-governance.md) |
| 14 | Release (MUST) | [release-and-governance.md](.agents/rules/release-and-governance.md) |
| 15 | Reentrant Loop State (MUST) | [persistence-and-loops.md](.agents/rules/persistence-and-loops.md) |
| 16 | API Exposure (Minimum-Exposure) (MUST) | [package-boundaries.md](.agents/rules/package-boundaries.md) |
| 17 | Docstrings (MUST) | [code-style.md](.agents/rules/code-style.md) |

## 📁 Rules Files

| File | Contents |
|------|----------|
| [development-process.md](.agents/rules/development-process.md) | Design docs, ecosystem-first, test location, verification, cleanse→verify→fix, workflow |
| [package-boundaries.md](.agents/rules/package-boundaries.md) | DAG, placement table, import allow/deny, hard bans, API exposure |
| [code-style.md](.agents/rules/code-style.md) | Terminology, no keyword heuristics, docstrings, code style |
| [persistence-and-loops.md](.agents/rules/persistence-and-loops.md) | Unified persistence backend, reentrant loop state |
| [release-and-governance.md](.agents/rules/release-and-governance.md) | AI attribution, drift governance, changelog, release process |
| [project-reference.md](.agents/rules/project-reference.md) | Structure, quick reference, plugin system, what NOT to implement |
